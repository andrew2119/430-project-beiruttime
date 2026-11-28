"""Authenticated bounded upstream reads for private service commands."""
import asyncio
import os
from functools import lru_cache
from datetime import datetime, timedelta

from bt_contracts.orders.allocation import CustodyReceipt
from bt_contracts.orders.allocation.v3 import CurrentCommitment
from bt_contracts.orders.journal.v2 import PaidOrderFactV2
from bt_contracts.orders.journal.v3 import FinancialReadiness
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import HTTPException, Request
from bt_bulkheads import DependencyClient, Unavailable
from bt_runtime.principal import CurrentPrincipal, current_principal, require_scope
from uuid import UUID

def bearer(request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    return token


def client(request, service, *, boundary=None):
    dependency = boundary or service
    name = 'service_source_client_' + dependency
    if not hasattr(request.app.state, name):
        setattr(request.app.state, name, DependencyClient(dependency,
            os.getenv('BT_' + service.upper().replace('-', '_') + '_URL', 'http://' + service + ':8000'),
            timeout=1.2, concurrency=4))
    return getattr(request.app.state, name)


async def personal_identity(request: Request):
    value = await current_principal(client(request, 'identity'), bearer(request), request.state.request_id)
    if isinstance(value, Unavailable):
        raise HTTPException(503)
    return value


async def identity(request: Request):
    selected = request.query_params.get('organization_id')
    if selected is not None:
        try:
            selected = UUID(selected)
        except ValueError:
            raise HTTPException(422) from None
        try:
            value = CurrentPrincipal.model_validate(await read(request, 'identity', f'/internal/v1/principal?organization_id={selected}'))
        except (ValueError, ConnectionError, TimeoutError):
            raise HTTPException(503) from None
        if value.actor.organization_id != selected:
            raise HTTPException(403)
        return value
    return await personal_identity(request)


async def principal(request: Request):
    return await business_principal(request, {'business.jobs.write'})


async def records_principal(request: Request):
    return await business_principal(request, {'business.records.read', 'business.jobs.write'})


async def business_principal(request, permissions):
    value = await identity(request)
    org = value.actor.organization_id
    if org is None:
        eligible = {grant.organization_id for grant in value.organization_grants
                    if grant.organization_id in value.organizations and permissions.intersection(grant.permissions)}
        if len(eligible) == 1:
            org = eligible.pop()
            value = value.model_copy(update={'actor': value.actor.model_copy(update={'organization_id': org})})
    if org is None:
        raise HTTPException(403)
    permission = next((permission for grant in value.organization_grants
                       if grant.organization_id == org
                       for permission in grant.permissions if permission in permissions), None)
    if permission is None:
        raise HTTPException(403)
    require_scope(value, permission, org)
    return value


async def read(request, service, path):
    response = await client(request, service).request('GET', path,
        headers={'Authorization': 'Bearer ' + bearer(request), 'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable) or response.status_code not in (200, 401, 403):
        raise ConnectionError('source_unavailable')
    if response.status_code in (401, 403):
        raise HTTPException(response.status_code)
    return object_body(response)


@lru_cache(maxsize=1)
def service_verification_key():
    # The deployment provides the shared service signing identity.
    key = os.getenv('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if not key:
        raise ValueError('service_authorization_unavailable')
    signing_key = load_pem_private_key(key.encode(), password=None)
    if not isinstance(signing_key, RSAPrivateKey):
        raise ValueError('service_authorization_unavailable')
    return signing_key.public_key()


def service(request, allowed):
    import jwt
    settings = request.app.state.settings
    token = bearer(request)
    try:
        key = settings.service_auth_public_key or service_verification_key()
    except (TypeError, ValueError):
        raise HTTPException(503) from None
    try:
        claims = jwt.decode(token, key, algorithms=['RS256'],
            audience='service-operations', issuer=settings.auth_issuer,
            options={'require': ['sub','type','iss','aud','iat','exp']})
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if claims['type'] != 'service' or claims['sub'] not in allowed:
        raise HTTPException(403)
    return claims['sub']


def service_headers(request, destination):
    import time
    import jwt
    key = os.getenv('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if not key:
        raise ConnectionError('service_authorization_unavailable')
    now = int(time.time())
    token = jwt.encode({'sub': 'service-operations', 'type': 'service',
        'iss': request.app.state.settings.auth_issuer, 'aud': destination, 'iat': now, 'exp': now+60}, key, algorithm='RS256')
    return {'Authorization': 'Bearer ' + token, 'X-Request-ID': request.state.request_id}


async def internal_read(request, destination, path, *, boundary=None, preserve_denial=False, missing_current=False):
    dependency = client(request, destination, boundary=boundary) if boundary else client(request, destination)
    response = await dependency.request('GET', path, headers=service_headers(request, destination))
    if preserve_denial and not isinstance(response, Unavailable) and response.status_code in (401, 403):
        raise HTTPException(response.status_code)
    if missing_current and not isinstance(response, Unavailable) and response.status_code == 409:
        return False
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise ConnectionError('source_unavailable')
    return object_body(response)


def object_body(response):
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError('invalid_source')
        return value
    except ValueError:
        raise ConnectionError('source_unavailable') from None


async def official_business(request, organization_id, capability):
    response = await client(request, 'identity').request('GET', f'/v1/businesses/{organization_id}',
        headers={'X-Request-ID': request.state.request_id})
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise ConnectionError('source_unavailable')
    business = object_body(response)
    capabilities = business.get('capabilities')
    if (business.get('id') != str(organization_id) or business.get('state') != 'active'
            or business.get('platform_onboarded') is not True
            or business.get('authenticated_business') is not True
            or not isinstance(capabilities, list) or capability not in capabilities):
        raise ConnectionError('business_unavailable')
    return business


async def current_commitment(request, order_id):
    raw = await internal_read(request, 'orders', f'/internal/v3/orders/{order_id}/commitment')
    try:
        return CurrentCommitment.model_validate(raw)
    except ValueError:
        raise ConnectionError('source_unavailable') from None


def require_assessment_fee_commitment(commitment, opening, buyer_id):
    if (commitment.current is not True
            or (commitment.order_id, commitment.organization_id, commitment.watch_id, commitment.watch_revision,
                commitment.buyer_id,
                commitment.quote_id, commitment.quote_revision) != (
                opening.order_id, opening.organization_id, opening.watch_id, opening.watch_revision,
                buyer_id,
                opening.quote_id, opening.quote_revision)):
        raise HTTPException(409)


async def current_order_facts(request, order_id):
    path = f'/internal/v3/orders/{order_id}'
    commitment, financial = await asyncio.gather(
        current_commitment(request, order_id),
        internal_read(request, 'orders', path + '/financial-readiness'),
    )
    try:
        return commitment, FinancialReadiness.model_validate(financial)
    except ValueError:
        raise ConnectionError('source_unavailable') from None


async def paid_order(request, order_id):
    raw = await internal_read(request, 'orders', f'/internal/v2/orders/{order_id}/paid-fact')
    try:
        return PaidOrderFactV2.model_validate(raw)
    except ValueError:
        raise ConnectionError('source_unavailable') from None


def assigned_custody(authority, order_id, organization_id, now):
    """Validate the custody projection of a signed, actor-bound job read."""
    try:
        raw = authority['custody_receipt']
        receipt = CustodyReceipt.model_validate(raw)
        if (raw['valid'] is not True or authority['custody_current'] is not True
                or type(authority['custody_revision']) is not int
                or (receipt.id, receipt.order_id, receipt.organization_id, receipt.revision) != (
                    UUID(str(authority['custody_receipt_id'])), order_id, organization_id,
                    authority['custody_revision'])
                or receipt.received_at > now):
            raise ValueError('custody_binding')
        return receipt
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ConnectionError('custody_unavailable') from None


async def verified_custody(request, assigned):
    """Check the assigned receipt through the reviewer's audited Orders read."""
    response = await client(request, 'orders').request(
        'GET', f'/v1/custody/receipts/{assigned.id}',
        headers={'Authorization': 'Bearer ' + bearer(request), 'X-Request-ID': request.state.request_id},
    )
    if not isinstance(response, Unavailable) and response.status_code in (401, 403):
        raise HTTPException(403)
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise ConnectionError('custody_unavailable')
    try:
        current = CustodyReceipt.model_validate(response.json())
    except ValueError:
        raise ConnectionError('custody_unavailable') from None
    if current != assigned:
        raise ConnectionError('custody_unavailable')
    return current


def accepted_work_lines(quote, selected, required):
    """Check that current work covers every selected line of the accepted quote."""
    try:
        quoted = quote['lines']
        if not isinstance(quoted, list) or not 1 <= len(quoted) <= 40:
            return False
        if not isinstance(selected, (list, tuple)) or not 1 <= len(selected) <= 40:
            return False
        lines = {}
        for line in quoted:
            line_id = UUID(line['id'])
            if line_id in lines or type(line['mandatory']) is not bool:
                return False
            lines[line_id] = line['mandatory']
        chosen = [UUID(line) for line in selected]
        needed = {UUID(str(line)) for line in required}
        mandatory = {line for line, required in lines.items() if required}
        return (len(chosen) == len(needed) and set(chosen) == needed
                and mandatory <= needed <= lines.keys())
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def accepted_payment_matches(quote, paid_total):
    """Bind the held payment to the buyer's accepted payable."""
    try:
        payable = quote['decision']['amounts']['payable_minor']
    except (KeyError, TypeError):
        return False
    return type(payable) is int and payable > 0 and payable == paid_total


def exact_held_payment(commitment, financial, paid):
    return (paid.paid is True and commitment.current is True
            and paid.state == commitment.state == financial.state == 'paid_held'
            and financial.movement_status == 'none' and financial.reserved_minor == 0
            and financial.held_minor == paid.total_minor > 0)


def quality_quote_matches(job):
    try:
        quote = job['accepted_quote']
        decision = quote['decision']
        return (quote['id'] == job['quote_id']
                and quote['organization_id'] == job['organization_id']
                and all(type(value) is int and value == job[key] for key, value in (
                    ('quote_revision', quote['revision']), ('source_revision', quote['source_revision']),
                    ('policy_revision', quote['policy']['revision']),
                ))
                and quote['currency'] == 'USD'
                and quote['state'] == decision['state'] == 'accepted'
                and quote['buyer_id'] == decision['actor_id']
                and accepted_work_lines(quote, decision['selected_line_ids'], job['required_line_ids']))
    except (KeyError, TypeError):
        return False


async def close_clients(app, stop):
    await stop.wait()
    await asyncio.gather(*(value.aclose() for key, value in app.state._state.items()
                          if key.startswith('service_source_client_')))


# Private producer boundaries. A producer without the corresponding route
# remains unavailable. Never substitute a broader business grant for assignment.
CURRENT_OPERATIONS = {
    'assessment_qualification': ('identity', '/internal/v1/assessment-qualification',
                                 ('actor_id', 'organization_id', 'request_id')),
    'assessment_replacement_eligibility': (
        'identity', '/internal/v1/assessment-replacement-eligibility',
        ('actor_id', 'organization_id', 'request_id', 'source_assignee_id', 'assignment_revision')),
    'assessment_followup': ('identity', '/internal/v1/assessment-followup',
                            ('organization_id', 'request_id', 'operation_id')),
    'maintenance_assessment_fee_binding': ('orders', '/internal/v1/maintenance-assessment-fee-binding',
                                           ('actor_id', 'organization_id', 'order_id', 'receipt_id')),
    'maintenance_fee_policy': ('catalog', '/internal/v1/maintenance-assessment-fee-policy', ('organization_id', 'brand_id')),
    'maintenance_historical_owner': ('catalog', '/internal/v1/maintenance-historical-owner', ('actor_id', 'watch_id')),
    'maintenance_accepted_fee': ('pricing', '/internal/v1/assessment-fee-decisions',
                                 ('operation_id', 'request_id', 'request_revision', 'buyer_id', 'organization_id',
                                  'offer_id', 'offer_revision')),
    'maintenance_context': ('catalog', '/internal/v1/maintenance-context', ('actor_id', 'watch_id', 'brand_id')),
    'maintenance_admission': ('catalog', '/internal/v1/maintenance-admission',
                              ('actor_id', 'watch_id', 'organization_id', 'operation_id', 'intervention', 'brand_id')),
    'intake_current_custody': ('orders', '/internal/v1/intake-current-custody',
                               ('actor_id', 'organization_id', 'order_id', 'receipt_id')),
    'maintenance_staff_grant': ('identity', '/internal/v1/maintenance-staff-grant', ('actor_id', 'organization_id')),
    'maintenance_precharge_custody': ('orders', '/internal/v1/maintenance-precharge-custody',
                                     ('actor_id', 'organization_id', 'request_id', 'order_id', 'receipt_id')),
    'repair_custody_transition': ('orders', '/internal/v1/repair-custody-transition',
                                 ('actor_id', 'organization_id', 'assessment_order_id', 'repair_order_id',
                                  'watch_id', 'assessment_receipt_id')),
    'maintenance_delivery_recovery_access': ('identity', '/internal/v1/maintenance-delivery-recovery-access',
                                             ('actor_id',)),
    'intake_opening_authority': ('orders', '/internal/v1/intake-opening-authority',
                                 ('actor_id', 'organization_id', 'order_id')),
    'intake_record_access': ('orders', '/internal/v1/intake-record-access',
                             ('actor_id', 'organization_id', 'order_id', 'permission')),
    'intake_readable_orders': ('orders', '/internal/v1/intake-readable-orders',
                               ('actor_id', 'organization_id')),
    'work_authority': ('orders', '/internal/v1/service-work-authority',
                       ('job_id', 'actor_id', 'organization_id')),
    'work_receipt_access': ('orders', '/internal/v1/service-work-receipt-access',
                            ('job_id', 'actor_id', 'organization_id', 'watch_id')),
    'quality_reviewer_authority': ('orders', '/internal/v1/service-quality-reviewer-authority',
                                   ('job_id', 'actor_id', 'organization_id')),
    'quality_job_authority': ('orders', '/internal/v1/service-quality-authority',
                              ('job_id', 'actor_id', 'organization_id')),
}


async def prerequisite(request, name, *args):
    """Read a signed, request-bound producer response or fail closed."""
    from urllib.parse import urlencode

    provider = getattr(request.app.state, name, None)
    async with asyncio.timeout(1.2):
        if provider is not None:
            return await provider(*args)
        if name == 'work_hold_receipt':
            operation_id, = args
            response = await client(request, 'orders', boundary='work_hold').request(
                'GET', f'/internal/v1/service-work-holds/operations/{operation_id}',
                headers=service_headers(request, 'orders'))
            if isinstance(response, Unavailable):
                raise ConnectionError('hold_unavailable')
            if response.status_code == 404:
                error = object_body(response).get('error')
                if isinstance(error, dict) and error.get('code') == 'operation_unknown':
                    return None
            if response.status_code != 200:
                raise ConnectionError('hold_unavailable')
            return object_body(response)
        if name == 'work_hold':
            command, = args
            headers = service_headers(request, 'orders')
            headers['Idempotency-Key'] = str(command.operation_id)
            response = await client(request, 'orders', boundary='work_hold').request(
                'POST', '/internal/v1/service-work-holds',
                headers=headers, json=command.model_dump(mode='json'))
            if isinstance(response, Unavailable) or response.status_code not in (200, 201):
                raise ConnectionError('hold_unavailable')
            return object_body(response)

        if name in ('maintenance_opening_fence', 'diagnosis_recovery_fence'):
            from hashlib import sha256

            raw, = args
            if name == 'maintenance_opening_fence':
                route, status, outcome, error = ('/internal/v1/maintenance-opening-fences',
                                               409, 'changed', 'opening_fence_unavailable')
            else:
                route, status, outcome, error = ('/internal/v1/intake-diagnosis-recovery-fences',
                                               403, 'denied', 'diagnosis_recovery_unavailable')
            response = await client(request, 'orders', boundary=name).request('POST', route,
                headers=service_headers(request, 'orders') | {'Content-Type': 'application/json'}, content=raw)
            if isinstance(response, Unavailable):
                raise ConnectionError(error)
            if response.status_code == status and object_body(response) == {
                    'binding_hash': sha256(raw).hexdigest(), 'status': outcome}:
                return False
            if response.status_code != 200:
                raise ConnectionError(error)
            return object_body(response)
        if name in ('maintenance_intake_grant_fence', 'maintenance_precharge_custody_fence', 'diagnosis_write_fence'):
            from hashlib import sha256

            raw, = args
            destination, route = {
                'maintenance_intake_grant_fence': ('identity', '/internal/v1/maintenance-intake-grant-fences'),
                'maintenance_precharge_custody_fence': ('orders', '/internal/v1/maintenance-precharge-custody-fences'),
                'diagnosis_write_fence': ('orders', '/internal/v1/intake-diagnosis-write-fences'),
            }[name]
            response = await client(request, destination, boundary=name).request('POST', route,
                headers=service_headers(request, destination) | {'Content-Type': 'application/json'}, content=raw)
            if isinstance(response, Unavailable):
                raise ConnectionError('authority_unavailable')
            if response.status_code == 409 and destination == 'orders':
                change = object_body(response)
                if change == {'binding_hash': sha256(raw).hexdigest(), 'status': 'changed'}:
                    return change if name == 'maintenance_precharge_custody_fence' else False
            if response.status_code != 200:
                raise ConnectionError('authority_unavailable')
            return object_body(response)
        if name == 'maintenance_destination_qualification_fence':
            raw, = args
            return await maintenance_destination_qualification(request, raw)
        destination, path, fields = CURRENT_OPERATIONS[name]
        # Work freshness is validated locally against the receipt deadline.
        if name == 'work_authority':
            args = args[:-1]
        if name == 'maintenance_context' and len(args) == 2:
            args = (*args, None)
        parameters = dict(zip(fields, args, strict=True))
        if name == 'work_receipt_access' and parameters['watch_id'] is None:
            del parameters['watch_id']
        if name == 'maintenance_context' and parameters['brand_id'] is None:
            del parameters['brand_id']
        if name == 'maintenance_accepted_fee':
            path += '/' + str(UUID(str(parameters.pop('operation_id'))))
        query = urlencode(parameters)
        result = await internal_read(
            request, destination, f'{path}?{query}', boundary=name,
            preserve_denial=name in {
                'quality_job_authority', 'quality_reviewer_authority', 'intake_current_custody',
                'intake_record_access', 'intake_readable_orders', 'maintenance_staff_grant',
                'maintenance_precharge_custody', 'maintenance_delivery_recovery_access', 'repair_custody_transition',
            },
            missing_current=name in ('intake_current_custody', 'maintenance_precharge_custody', 'repair_custody_transition'),
        )
        if name == 'maintenance_delivery_recovery_access':
            check_delivery_grant(result, args[0])
        return result


async def maintenance_destination_qualification(request, raw):
    from hashlib import sha256

    error = 'assessment_destination_qualification_unavailable'
    try:
        from bt_contracts.identity.maintenance_authorizations.destination import (
            DestinationQualificationFence, DestinationQualificationProof,
        )
        intent = DestinationQualificationFence.model_validate_json(raw)
    except (ImportError, ValueError):
        raise ConnectionError(error) from None
    if intent.hold_until.utcoffset() != timedelta(0) or 'purpose' not in intent.binding.model_fields_set:
        raise ConnectionError(error)
    response = await client(request, 'identity', boundary='maintenance_destination_qualification_fence').request(
        'POST', '/internal/v1/service-job-qualification-fences',
        headers=service_headers(request, 'identity') | {'Content-Type': 'application/json'}, content=raw)
    if isinstance(response, Unavailable) or response.status_code != 200:
        raise ConnectionError(error)
    try:
        result = object_body(response)
        proof = DestinationQualificationProof.model_validate(result)
    except (ConnectionError, ValueError):
        raise ConnectionError(error) from None
    b = intent.binding
    if (proof.binding_hash != sha256(raw).hexdigest() or proof.held_until.utcoffset() != timedelta(0)
            or proof.held_until < intent.hold_until or proof.result.seller_id != b.organization_id
            or (proof.result.seller_type == 'brand') != (b.organization_id == b.brand_id)):
        raise ConnectionError(error)
    return result


def check_delivery_grant(result, actor_id):
    try:
        if result.get('actor_id') != str(actor_id) or type(result.get('allowed')) is not bool:
            raise ValueError('unbound_recovery_actor')
        if result['allowed'] is True:
            held_until = datetime.fromisoformat(result['held_until'])
            if held_until.utcoffset() != timedelta(0):
                raise ValueError('utc_recovery_deadline_required')
    except (TypeError, ValueError, AttributeError, KeyError):
        raise ConnectionError('maintenance_recovery_grant_unavailable') from None
