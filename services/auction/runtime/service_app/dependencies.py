"""One bounded client per dependency; fixture transports are test injection only."""
import os
import time
from uuid import UUID
import jwt
from fastapi import HTTPException, Request
from pydantic import ValidationError
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import CurrentPrincipal, current_principal
from .fee_quote import BidFeeSnapshot


class Dependencies:
    def __init__(self, clients=None, service_key=None):
        self.service_key = service_key if service_key is not None else os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
        self.clients = clients or {name: DependencyClient(name, os.environ.get(
            f'{name.upper()}_API_URL', os.environ.get(f'{name.upper()}_URL', f'http://{name}:8000')), timeout=1.2, concurrency=4)
            for name in ('identity', 'catalog', 'pricing', 'orders')}

    async def json(self, name, method, path, request, *, missing=False, **kwargs):
        result = await self.clients[name].request(method, path, headers={
            'Authorization': request.headers.get('authorization', ''),
            'X-Request-ID': request.state.request_id,
            **kwargs.pop('headers', {})}, **kwargs)
        if isinstance(result, Unavailable):
            raise PublicError('dependency_unavailable', 'A required service is unavailable.', status=503)
        if result.status_code >= 500:
            raise PublicError('dependency_unavailable', 'A required service is unavailable. Retry the same operation.', status=503)
        if result.status_code in (401, 403):
            raise AccessDenied('Upstream refused current access')
        if result.status_code == 404 and missing:
            return None
        if result.status_code == 404:
            raise PublicError('prerequisite_missing', 'A required record is not available.', status=409)
        if result.status_code >= 300:
            raise PublicError('prerequisite_denied', 'A current prerequisite was refused.', status=409)
        try:
            data = result.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ValueError:
            raise PublicError('dependency_unavailable', 'A required service is unavailable.', status=503) from None

    async def principal(self, request: Request):
        scheme, _, token = request.headers.get('authorization', '').partition(' ')
        if scheme.lower() != 'bearer' or not token or len(token) > 8192:
            raise HTTPException(401)
        selected = request.query_params.get('organization_id')
        if selected:
            try:
                organization = UUID(selected)
            except ValueError:
                raise PublicError('invalid_organization', 'Select a valid organization.', status=422) from None
            data = await self.json('identity', 'GET', f'/internal/v1/principal?organization_id={organization}', request)
            try:
                principal = CurrentPrincipal.model_validate(data)
            except ValidationError:
                raise PublicError('identity_unavailable', 'Current access cannot be verified.', status=503) from None
            if principal.actor.organization_id != organization:
                raise AccessDenied('Represented organization could not be verified')
        else:
            principal = await current_principal(self.clients['identity'], token, request.state.request_id)
        if isinstance(principal, Unavailable):
            raise PublicError('identity_unavailable', 'Current access cannot be verified.', status=503)
        return principal

    async def bid_admission(self, request, tx, principal):
        def unavailable():
            return PublicError('admission_unavailable', 'Current bid admission cannot be confirmed.', status=503)

        try:
            from bt_contracts.identity.marketplace_admission.v1 import hold_deadline, signed_body, verify_hold
        except ImportError:
            raise unavailable() from None
        try:
            session_id = UUID(principal.actor.session_id)
        except (TypeError, ValueError):
            raise AccessDenied('A current marketplace session is required') from None
        deadline = await hold_deadline(tx)
        raw, digest = signed_body({'actor_id': str(principal.actor.subject_id), 'session_id': str(session_id)}, deadline)
        try:
            reply = await self.json('identity', 'POST', '/internal/v1/marketplace-admission', request,
                headers={**self.service_headers(request, 'identity'), 'Content-Type': 'application/json'}, content=raw)
        except (AccessDenied, PublicError, HTTPException):
            raise unavailable() from None
        if set(reply) != {'binding_hash', 'held_until', 'status'}:
            raise unavailable()
        verify_hold(reply, digest, deadline)
        if reply['status'] == 'suspended':
            raise PublicError('bid_permission_required', 'Current access does not permit new bids.', status=403)
        if reply['status'] != 'held' or await tx.fetchval('SELECT clock_timestamp()') >= deadline:
            raise unavailable()

    async def listing(self, request, listing_id):
        # Catalog's canonical PublicListing V1 names the physical watch and
        # organization explicitly and includes its immutable Orders registration.
        publication = await self.json('catalog', 'GET', f'/v1/listings/{listing_id}', request)
        try:
            registration = publication['registration']
            watch_id = UUID(publication['physical_watch_id'])
            seller_id = UUID(publication['seller_id'])
            organization = publication['organization_id']
            demo = publication.get('is_demo')
            if organization is not None:
                organization = str(UUID(organization))
            if (UUID(publication['id']) != listing_id or type(publication['revision']) is not int
                    or publication['revision'] < 1 or UUID(registration['watch_id']) != watch_id
                    or UUID(registration['listing_id']) != listing_id
                    or registration['sale_mode'] != 'auction'
                    or publication['facts']['sale_mode'] != 'auction'
                    or publication['facts']['currency'] != 'USD'):
                raise ValueError()
            return {'id':str(listing_id), 'watch_id':str(watch_id),
                'seller_id':str(seller_id), 'seller_organization_id':organization,
                'status':publication['status'], 'revision': publication['revision'],
                # Catalog validates the registration's flag at publication and
                # retains it on the public listing, not in the registration reference.
                'is_demo': demo if type(demo) is bool else None}
        except (KeyError, TypeError, ValueError):
            raise PublicError('catalog_unavailable', 'The listing cannot currently be verified.', status=503) from None

    def service_headers(self, request, audience):
        if not self.service_key:
            raise PublicError('service_auth_unavailable', 'A required service is unavailable.', status=503)
        now = int(time.time())
        token = jwt.encode({'sub': 'auction', 'type': 'service', 'iss': request.app.state.settings.auth_issuer,
            'aud': audience, 'iat': now, 'exp': now + 60}, self.service_key, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    async def fence_state(self, request, watch_id, listing_id, auction_id):
        result = await self.json('orders', 'GET',
            f'/internal/v2/watches/{watch_id}', request, missing=True,
            headers=self.service_headers(request, 'orders'))
        if result is None:
            # Rolling upgrade only: legacy fences are already committed, never
            # downgraded to the new withdrawable/uncommitted auction-open state.
            result = await self.json('orders', 'GET',
                f'/internal/v1/watches/{watch_id}/fence?source_id={auction_id}', request,
                headers=self.service_headers(request, 'orders'))
            result['api_version'] = 1
            result['source_id'] = str(auction_id) if result.get('source_matches') is True else None
            result['auction_committed'] = result.get('status') == 'fenced'
        else:
            result['api_version'] = 2
            result['source_matches'] = result.get('source_id') == str(auction_id)
        if (result.get('watch_id') != str(watch_id) or result.get('listing_id') != str(listing_id)
                or type(result.get('revision')) is not int or result['revision'] < 1):
            raise PublicError('orders_unavailable', 'The sale commitment cannot be verified.', status=503)
        if result['api_version'] == 2 and (type(result.get('listing_revision')) is not int
                or result['listing_revision'] < 1 or type(result.get('auction_committed')) is not bool):
            raise PublicError('orders_unavailable', 'The current commitment binding cannot be verified.', status=503)
        # V2's required watch/source/revision binding is authoritative. Some
        # compatible V2 reads omit V1's sale_mode; an explicit other mode denies.
        if (result['api_version'] == 1 and result.get('sale_mode') != 'auction') or result.get('sale_mode') not in (None, 'auction'):
            raise PublicError('sale_mode_denied', 'The watch is not registered for auction.', status=409)
        return result

    @staticmethod
    def opening_command(intent):
        return dict(operation_key='auction-open:' + intent['auction_id'], watch_id=intent['watch_id'], listing_id=intent['listing_id'],
                    listing_revision=intent['listing_revision'], expected_revision=intent['watch_revision'],
                    source_id=intent['auction_id'], kind='auction_open', reason='Open ordinary auction')

    async def start_commitment(self, request, intent, organization):
        result = await self.start_command(request, '/internal/v2/commitments', self.opening_command(intent))
        if result.get('status') == 'denied':
            return result
        watch = result.get('watch')
        if result.get('status') != 'succeeded' or not isinstance(watch, dict):
            raise self.start_pending()
        expected = dict(watch_id=intent['watch_id'], listing_id=intent['listing_id'],
                        listing_revision=intent['listing_revision'], seller_id=intent['seller_id'],
                        organization_id=str(organization) if organization else None, source_id=intent['auction_id'],
                        source_kind='auction_open', status='fenced', revision=intent['watch_revision']+1)
        if (any(watch.get(name) != value for name, value in expected.items())
                or type(watch.get('revision')) is not int or type(watch.get('listing_revision')) is not int
                or watch.get('auction_committed') is not False or watch.get('sale_mode') != 'auction'):
            raise self.start_pending()
        return result

    async def release_start_commitment(self, request, intent, open_key):
        scope = dict(operation_key='auction-open-release:' + intent['auction_id'], open_operation_id=intent['open_operation_id'],
                     auction_id=intent['auction_id'], listing_id=intent['listing_id'], listing_revision=intent['listing_revision'],
                     watch_id=intent['watch_id'], expected_revision=intent['watch_revision']+1)
        result = await self.start_command(request, '/internal/v2/auction-open-releases',
            dict(scope, open_operation_key=open_key, reason=intent['release_reason']))
        if (result.get('state') not in ('released', 'superseded') or any(result.get(key) != value for key, value in scope.items())
                or type(result.get('listing_revision')) is not int or type(result.get('expected_revision')) is not int):
            raise self.start_pending()

    async def expire_start_commitment(self, request, intent):
        key = 'auction-open-expire:' + intent['auction_id']
        result = await self.start_command(request, '/internal/v2/auction-open-expirations',
            dict(operation_key=key, original=self.opening_command(intent)))
        expected = dict(operation_key=key, auction_id=intent['auction_id'], watch_id=intent['watch_id'],
                        listing_id=intent['listing_id'], listing_revision=intent['listing_revision'],
                        expected_revision=intent['watch_revision'])
        if (result.get('state') not in ('abandoned', 'released', 'superseded')
                or any(result.get(name) != value for name, value in expected.items())
                or type(result.get('listing_revision')) is not int or type(result.get('expected_revision')) is not int):
            raise self.start_pending()

    @staticmethod
    def start_pending():
        return PublicError('sale_mode_pending', 'The sale commitment is not confirmed. Retry the original request.', status=503)

    async def start_command(self, request, path, payload):
        try:
            result = await self.json('orders', 'POST', path, request,
                headers={**self.service_headers(request, 'orders'), 'Idempotency-Key': payload['operation_key']}, json=payload)
            if str(UUID(result['id'])) != result['id']:
                raise ValueError()
            return result
        except (KeyError, TypeError, ValueError, PublicError, AccessDenied, HTTPException):
            raise self.start_pending() from None

    async def check_fence(self, request, lot):
        result = await self.fence_state(request, lot['watch_id'], lot['listing_id'], lot['id'])
        if (result.get('status') != 'fenced' or result.get('source_matches') is not True
                or ('listing_revision' in lot and result['api_version'] == 2
                    and result['listing_revision'] != lot['listing_revision'])):
            raise PublicError('sale_mode_denied', 'The watch is not committed to this auction.', status=409)

    async def bid_quote(self, request, command, lot, principal):
        quote = await self.json('pricing', 'GET', f'/v1/quotes/{command.fee_quote_id}', request)
        try:
            snapshot = BidFeeSnapshot.model_validate(quote)
        except ValidationError:
            raise PublicError('pricing_unavailable', 'The fee preview cannot currently be verified.', status=503) from None
        valid = (snapshot.id == command.fee_quote_id and snapshot.owner_id == principal.actor.subject_id
            and snapshot.purpose == 'bid' and snapshot.subject_id == lot['id']
            and snapshot.subject_revision == command.expected_revision and snapshot.price_minor == command.amount_minor
            and snapshot.currency == lot['currency']
            and snapshot.sample is True and snapshot.source == 'sample' and snapshot.source_verified is False)
        if not valid:
            raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
        if snapshot.reviewed_at is None:
            raise PublicError('fee_review_required', 'Confirm the retained fee preview before bidding.', status=409)
        return snapshot

    async def fee(self, request, command, lot, principal, now, *, maximum_binding=None):
        snapshot = await self.bid_quote(request, command, lot, principal)
        if maximum_binding is not None and (snapshot.revision != maximum_binding['quote_revision']
                or snapshot.policy is None or str(snapshot.policy.revision) != maximum_binding['policy_revision']):
            raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
        if snapshot.expires_at <= now or command.expected_revision != lot['revision']:
            raise PublicError('fee_preview_required', 'Review a current fee preview for this amount.', status=409)
        return snapshot.expires_at

    async def contact(self, request):
        result = await self.json('identity', 'GET', '/v1/contacts', request)
        # Identity contacts v1: only current verification flags qualify, never pending metadata/recipients.
        if type(result.get('email_verified')) is not bool or type(result.get('phone_verified')) is not bool:
            raise PublicError('identity_unavailable', 'Current contact verification is unavailable.', status=503)
        if not (result['email_verified'] or result['phone_verified']):
            raise PublicError('verified_contact_required', 'Verify a current contact before this bid.', status=409)

    async def close(self):
        for client in self.clients.values():
            await client.aclose()
