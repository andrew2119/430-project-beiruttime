"""Accepted case-line transport tied to current diagnosis and retained consent."""
import json
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from bt_runtime.principal import require_scope
from bt_contracts.service.intake.current import RecordAccess, OpeningAuthority
from bt_runtime.app.db import unit_of_work
from bt_contracts.service.case_lines.acceptance import Acceptance
from bt_contracts.service.case_lines.v1 import Scope, ScopeReceipt, accepted_payable
from bt_contracts.service.maintenance.diagnosis import Line
from service_app.received_case import case_binding, retained_scope_submission
from service_app.sources import (
    current_commitment, identity, internal_read, paid_order, personal_identity, prerequisite, read,
)

router = APIRouter(prefix='/v1/case-lines')


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def access(request, tx, actor, row):
    if actor.actor.organization_id is None and actor.actor.subject_id == row['buyer_id']:
        return
    require_scope(actor, 'business.records.read', row['organization_id'])
    saved = decoded(row['body'])
    diagnosis = await tx.fetchval('SELECT body FROM service_diagnoses WHERE case_id=$1', UUID(saved['case_id']))
    if not diagnosis:
        raise HTTPException(403)
    order = UUID(decoded(diagnosis)['order_id'])
    try:
        facts = RecordAccess.model_validate(await prerequisite(request, 'intake_record_access', actor.actor.subject_id, row["organization_id"], order, 'read'))
    except (ValueError, ConnectionError, TimeoutError):
        raise HTTPException(503) from None
    if (facts.actor_id,facts.organization_id,facts.order_id,facts.permission,facts.allowed) != (actor.actor.subject_id,row['organization_id'],order,'read',True):
        raise HTTPException(403)


async def current_source(request, tx, saved, *, commitment=None):
    order = UUID(saved['order_id'])
    assessor = UUID(saved['actor_id'])
    organization = UUID(saved['organization_id'])
    try:
        opening = OpeningAuthority.model_validate(await prerequisite(request, 'intake_opening_authority', assessor, organization, order))
        assigned = RecordAccess.model_validate(await prerequisite(request, 'intake_record_access', assessor, organization, order, 'write'))
    except (ValueError, ConnectionError, TimeoutError):
        raise HTTPException(503) from None
    intake = await tx.fetchrow('SELECT * FROM technical_intakes WHERE id=$1 FOR SHARE', UUID(saved['case_id']))
    if not intake or intake['state'] != 'received' or intake['revision'] != saved['intake_revision']:
        raise HTTPException(409)
    if (assigned.actor_id, assigned.organization_id, assigned.order_id, assigned.permission,
            assigned.allowed, assigned.assignment_revision) != (
            assessor, organization, order, 'write', True, saved['assignment_revision']):
        raise HTTPException(409)
    expected = dict(actor_id=assessor, organization_id=organization, order_id=order,
        watch_id=UUID(saved['watch_id']), receipt_id=UUID(saved['receipt_id']),
        receipt_revision=saved['receipt_revision'], watch_revision=saved['watch_revision'],
        consent_revision=saved['consent_revision'], accepted_terms_revision=saved['accepted_terms_revision'],
        incident_revision=saved.get('incident_revision'))
    private = decoded(intake['private_record'])
    if (any(getattr(opening, key) != value for key, value in expected.items())
            or intake['order_id'] != order or intake['organization_id'] != organization
            or intake['custody_receipt_id'] != opening.receipt_id
            or intake['custody_revision'] != opening.receipt_revision
            or intake['received_at'] != opening.received_at
            or opening.received_at > datetime.now(timezone.utc)
            or not all((opening.current, opening.assigned, opening.permission,
                opening.customer_opening_permission, opening.accepted_assessment_fee,
                opening.customer_no_polish_acknowledged, private['diagnostic_opening_permission'],
                private['fee_acknowledged'], private['no_polish_acknowledged']))
            or private['currency'] != 'USD' or private['fee_minor'] != opening.accepted_fee_minor):
        raise HTTPException(409)

    if (saved.get('fee_quote_id'), saved.get('fee_quote_revision')) != (
            str(opening.quote_id), opening.quote_revision):
        raise HTTPException(409)
    binding = await case_binding(request, tx, UUID(saved['case_id']), opening, commitment=commitment)
    if any(str(getattr(binding, key)) != saved[key] for key in
           ('case_id', 'request_id', 'watch_id', 'buyer_id', 'order_id')):
        raise HTTPException(409)
    return intake


async def acknowledged_diagnosis(tx, case_id):
    return await tx.fetchrow(
        """SELECT d.* FROM service_diagnoses d
           JOIN service_diagnosis_operations o
             ON o.operation_id::text=d.body->>'operation_id'
            AND o.organization_id=d.organization_id
            AND o.actor_id::text=d.body->>'actor_id'
            AND o.receipt=d.body AND o.receipt @> o.command
           WHERE d.case_id=$1 FOR SHARE OF d, o""", case_id)


async def paid_source(request, tx, saved, scope, repair_order_id, payable, *, assessment=None):
    """Validate the received diagnosis and the commitment that now reserves the watch."""
    try:
        assessment_order = UUID(saved['order_id'])
        fee_quote = UUID(saved['fee_quote_id'])
        identifiers = tuple(UUID(scope[key]) for key in ('watch_id', 'actor_id', 'organization_id'))
        repair_quote = UUID(scope['quote_id'])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409) from None
    if (repair_order_id == assessment_order or repair_quote == fee_quote
            or saved['watch_id'] != scope['watch_id'] or saved['buyer_id'] != scope['actor_id']
            or saved['organization_id'] != scope['organization_id']
            or saved['request_id'] != scope['request_id']):
        raise HTTPException(409)
    assessor = UUID(saved['actor_id'])
    receipt_id = UUID(saved['receipt_id'])
    received_at = await tx.fetchval("""
        SELECT i.received_at FROM technical_intakes i
        JOIN service_diagnosis_operations o ON o.operation_id=$2 AND o.receipt=$3::jsonb
            AND o.actor_id=$4 AND o.organization_id=i.organization_id
        WHERE i.id=$1 AND i.order_id=$5 AND i.organization_id=$6
          AND i.state='received' AND i.revision=$7
          AND i.custody_receipt_id=$8 AND i.custody_revision=$9
          AND i.private_record @> '{"currency":"USD","diagnostic_opening_permission":true,
              "fee_acknowledged":true,"no_polish_acknowledged":true}'::jsonb
        FOR SHARE OF i
        """, UUID(saved['case_id']), UUID(saved['operation_id']), json.dumps(saved),
        assessor, assessment_order, identifiers[2], saved['intake_revision'],
        receipt_id, saved['receipt_revision'])
    if received_at is None:
        raise HTTPException(409)
    try:
        opening = OpeningAuthority.model_validate(await prerequisite(
            request, 'intake_opening_authority', assessor, identifiers[2], assessment_order))
    except (ValueError, ConnectionError, TimeoutError):
        raise HTTPException(503) from None
    if ((opening.actor_id, opening.organization_id, opening.order_id, opening.watch_id,
         opening.receipt_id, opening.receipt_revision, opening.received_at)
            != (assessor, identifiers[2], assessment_order, identifiers[0],
                receipt_id, saved['receipt_revision'], received_at)
            or not opening.assigned or not opening.permission
            or opening.received_at > datetime.now(timezone.utc)):
        raise HTTPException(409)
    try:
        if assessment is None:
            assessment = await current_commitment(request, assessment_order)
        repair = await current_commitment(request, repair_order_id)
        paid = await paid_order(request, repair_order_id)
    except (ConnectionError, TimeoutError):
        raise HTTPException(503) from None
    if ((assessment.order_id, assessment.watch_id, assessment.buyer_id,
         assessment.organization_id, assessment.quote_id, assessment.quote_revision)
            != (assessment_order, *identifiers, fee_quote, saved['fee_quote_revision'])
            or (repair.order_id, repair.watch_id, repair.buyer_id, repair.organization_id,
                repair.quote_id, repair.quote_revision)
            != (repair_order_id, *identifiers, repair_quote, scope['quote_revision'])
            or (paid.order_id, paid.watch_id, paid.buyer_id, paid.organization_id,
                paid.quote_id, paid.quote_revision, paid.revision)
            != (repair_order_id, *identifiers, repair_quote, scope['quote_revision'], repair.order_revision)
            or not repair.current or repair.state != 'paid_held' or not paid.paid
            or paid.state != 'paid_held' or paid.is_demo or paid.currency != 'USD'
            or paid.order_kind != 'service_job' or paid.total_minor != payable):
        raise HTTPException(409)


async def repair_commitment_order(request, watch_id):
    """Resolve the exact order from the watch's exclusive reservation."""
    try:
        watch = await internal_read(request, 'orders', f'/internal/v2/watches/{watch_id}')
        returned_watch_id = UUID(watch['watch_id'])
        source_id = watch['source_id']
        order_id = UUID(source_id) if source_id is not None else None
    except (ConnectionError, TimeoutError, KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(503) from None
    if (returned_watch_id != watch_id or watch.get('status') != 'reserved'
            or watch.get('source_kind') != 'service_job' or order_id is None):
        raise HTTPException(409)
    return order_id


async def submitted_revision(tx, request_id, buyer, organization, watch):
    revision = await tx.fetchval(
        """SELECT revision FROM maintenance_requests
           WHERE id=$1 AND actor_id=$2 AND organization_id=$3 AND watch_id=$4
             AND state='submitted' FOR SHARE""", request_id, buyer, organization, watch)
    if revision is None:
        raise HTTPException(409)
    return revision


async def scope_receipt(tx, saved, command=None):
    if command is not None:
        saved = {**saved, **{key: command[key] for key in
                             ('case_id', 'assessment_id', 'assessment_revision')}}
    if 'request_revision' in saved:
        return accepted_receipt(saved, saved['request_revision'])
    # Older acknowledgements retained the selection alongside the receipt fields.
    # Recover the binding from the immutable submission acknowledgement.
    revision = await tx.fetchval(
        """SELECT (o.result->>'revision')::integer FROM maintenance_requests r
           JOIN maintenance_request_operations o ON o.operation_id=r.operation_id
           WHERE r.id=$1 AND r.actor_id=$2 AND r.organization_id=$3 AND r.watch_id=$4
             AND o.result->>'state'='submitted'""",
        *(UUID(saved[key]) for key in ('request_id','actor_id','organization_id','watch_id')))
    if revision is None:
        raise HTTPException(409)
    return accepted_receipt(saved, revision)


def accepted_receipt(saved, request_revision):
    fields = {key: saved[key] for key in ScopeReceipt.model_fields if key in saved}
    fields.update(subject_id=saved['actor_id'], next_actor='business', request_revision=request_revision)
    result = ScopeReceipt.model_validate(fields).model_dump(mode='json')
    for key in ('case_id', 'assessment_id', 'assessment_revision'):
        if result[key] is None:
            del result[key]
    return result


def published_scope(saved):
    try:
        scope = Scope(
            request_id=saved['request_id'], request_revision=saved['request_revision'],
            revision=saved['revision'], accepted_line_ids=saved['accepted_line_ids'],
            lines=[dict(line_id=line['id'], description=line['label'], kind=line['kind'],
                        required=line['mandatory'], amount_minor=line['amount_minor'],
                        assessment_id=saved['assessment_id'],
                        assessment_revision=saved['assessment_revision']) for line in saved['lines']],
        )
        scope.accepted_total()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409) from None
    return scope


def matching_assessed_lines(quoted, assessed):
    def by_id(lines):
        result = {}
        for raw in lines:
            line = Line.model_validate({key: raw.get(key) for key in Line.model_fields})
            if line.id in result:
                raise ValueError('duplicate_line')
            result[line.id] = line
        return result

    try:
        return by_id(quoted) == by_id(assessed)
    except (AttributeError, TypeError, ValueError):
        return False


async def current_quote(request, quote_id, bindings, *, organization=None):
    try:
        path = f'/v1/repair-quotes/{quote_id}'
        if organization is not None:
            path += f'?organization_id={organization}'
        quote = await read(request, 'pricing', path)
    except (ConnectionError, TimeoutError):
        raise HTTPException(503) from None
    decision = quote.get('decision')
    if (quote.get('id') != str(quote_id) or quote.get('currency') != 'USD'
            or quote.get('state') != 'accepted' or not isinstance(decision, dict)
            or decision.get('state') != 'accepted'
            or decision.get('actor_id') != str(bindings['buyer_id'])
            or any(type(quote.get(key)) is not type(value) or quote[key] != value
                   for key, value in bindings.items())):
        raise HTTPException(409)
    return quote, decision


@router.post('/{request_id}/acceptance')
async def accept(request_id: UUID, body: Acceptance, request: Request,
                 actor=Depends(personal_identity), organization_id: UUID | None = None):
    if actor.actor.organization_id is not None or actor.actor.subject_id != body.actor_id or request_id != body.request_id:
        raise HTTPException(403)
    if organization_id is not None and organization_id != body.organization_id:
        raise HTTPException(403)
    async with unit_of_work(request.app.state.pool, lock_key=f'case-lines:{body.case_id}') as tx:
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', str(body.operation_id))
        prior = await tx.fetchrow('SELECT command,receipt FROM service_case_scope_operations WHERE operation_id=$1', body.operation_id)
        if prior:
            original = decoded(prior['command'])
            if original.get('actor_id') != str(body.actor_id):
                raise HTTPException(403)
            if original != body.model_dump(mode='json', exclude_none=True):
                raise HTTPException(409)
            return await scope_receipt(tx, decoded(prior['receipt']), original)
        # Pricing stores one immutable buyer decision per quote. A fresh
        # transport key for that decision recovers the original scope receipt.
        accepted = await tx.fetchrow("""
            SELECT command,receipt FROM service_case_scope_operations
            WHERE actor_id=$1 AND command @> $2::jsonb
              AND receipt->>'operation_id'=operation_id::text
              AND receipt->>'state'='accepted'
            ORDER BY (receipt->>'revision')::integer, operation_id
            LIMIT 1""", body.actor_id, json.dumps({
                'case_id': str(body.case_id), 'quote_id': str(body.quote_id),
            }))
        if accepted:
            original = decoded(accepted['command'])
            receipt = await scope_receipt(tx, decoded(accepted['receipt']), original)
            bindings = body.model_dump(mode='json', exclude={
                'operation_id', 'expected_revision', 'request_revision',
            })
            if (any(original.get(key) != value for key, value in bindings.items())
                    or body.request_revision not in (None, receipt['request_revision'])):
                raise HTTPException(409)
            await tx.execute('INSERT INTO service_case_scope_operations VALUES($1,$2,$3::jsonb,$4::jsonb)',
                body.operation_id, body.actor_id, body.model_dump_json(exclude_none=True), json.dumps(receipt))
            return receipt
        quote, decision = await current_quote(request, body.quote_id, {
            'source_id': str(body.case_id), 'assessment_id': str(body.assessment_id),
            'assessment_revision': body.assessment_revision, 'revision': body.quote_revision,
            'organization_id': str(body.organization_id), 'buyer_id': str(body.actor_id),
        })
        if quote.get('policy', {}).get('revision') != body.policy_revision:
            raise HTTPException(409)
        diagnosis = await acknowledged_diagnosis(tx, body.case_id)
        if not diagnosis or (diagnosis['request_id'],diagnosis['organization_id'],diagnosis['watch_id'],diagnosis['assessment_id'],diagnosis['revision']) != (body.request_id,body.organization_id,body.watch_id,body.assessment_id,body.assessment_revision):
            raise HTTPException(409)
        assessed = decoded(diagnosis['body'])
        if quote.get('source_revision') != diagnosis['revision'] or quote.get('diagnosis') != assessed['diagnosis']:
            raise HTTPException(409)
        lines = quote.get('lines', [])
        if not matching_assessed_lines(lines, assessed['lines']):
            raise HTTPException(409)
        selected = decision.get('selected_line_ids', [])
        if len(selected) != len(set(selected)) or not set(selected) <= {line['id'] for line in lines} or any(line['mandatory'] and line['id'] not in selected for line in lines):
            raise HTTPException(409)
        await current_source(request, tx, assessed)
        revision = await tx.fetchval('SELECT revision FROM service_case_scopes WHERE case_id=$1 FOR UPDATE', body.case_id) or 0
        if revision != body.expected_revision:
            raise HTTPException(409)
        result = {**body.model_dump(mode='json'), 'state':'accepted', 'revision':revision+1,
            'scope_revision':revision+1, 'accepted_line_ids':selected, 'lines':lines,
            'release_eligible':False}
        request_revision = await submitted_revision(
            tx, request_id, body.actor_id, body.organization_id, body.watch_id)
        if body.request_revision is not None and body.request_revision != request_revision:
            raise HTTPException(409)
        receipt = accepted_receipt(result, request_revision)
        result.update(receipt)
        result['total_minor'] = published_scope(result).accepted_total()
        try:
            result['payable_minor'] = accepted_payable(quote, result['total_minor'])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(409) from None
        encoded = json.dumps(result)
        await tx.execute('''INSERT INTO service_case_scopes VALUES($1,$2,$3,$4,$5,$6::jsonb)
            ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,body=excluded.body''',
            body.case_id, body.request_id, body.organization_id, body.actor_id, revision+1, encoded)
        await tx.execute('INSERT INTO service_case_scope_operations VALUES($1,$2,$3::jsonb,$4::jsonb)', body.operation_id, body.actor_id, body.model_dump_json(exclude_none=True), json.dumps(receipt))
        await tx.execute('INSERT INTO service_case_scope_outbox(operation_id,case_id,revision) VALUES($1,$2,$3)', body.operation_id, body.case_id, revision+1)
        return receipt


@router.get('/operations/{operation_id}')
async def lookup(operation_id: UUID, request: Request,
                 actor=Depends(personal_identity), organization_id: UUID | None = None):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT command,receipt FROM service_case_scope_operations WHERE operation_id=$1', operation_id)
        if not row:
            raise HTTPException(404)
        command = decoded(row['command'])
        scope = await tx.fetchrow('SELECT * FROM service_case_scopes WHERE case_id=$1', UUID(command['case_id']))
        if not scope or (organization_id is not None and scope['organization_id'] != organization_id):
            raise HTTPException(404)
        if actor.actor.subject_id != scope['buyer_id'] and organization_id is not None:
            actor = await identity(request)
        await access(request, tx, actor, scope)
        receipt = await scope_receipt(tx, decoded(row['receipt']), command)
    return receipt


@router.get('/{request_id}', response_model=Scope)
async def current(request_id: UUID, request: Request, actor=Depends(identity),
                  repair_order_id: UUID | None = None):
    async with unit_of_work(request.app.state.pool) as tx:
        row = await tx.fetchrow(
            'SELECT * FROM service_case_scopes WHERE request_id=$1 ORDER BY revision DESC LIMIT 1 FOR SHARE',
            request_id)
        if not row:
            raise HTTPException(404)
        await access(request, tx, actor, row)
        saved = decoded(row['body'])
        legacy = 'request_revision' not in saved
        if legacy:
            saved.update(await scope_receipt(tx, saved))
        case_id = UUID(saved['case_id'])
        acceptance = await tx.fetchrow("""
            SELECT command, receipt FROM service_case_scope_operations
            WHERE operation_id=$1 AND actor_id=$2
              AND $3::jsonb @> command AND $3::jsonb @> receipt
            FOR SHARE
            """, UUID(saved['operation_id']), row['buyer_id'], json.dumps(saved))
        if not acceptance:
            raise HTTPException(409)
        try:
            receipt = decoded(acceptance['receipt'])
            if legacy:
                receipt = await scope_receipt(tx, receipt, decoded(acceptance['command']))
            expected = accepted_receipt(saved, saved['request_revision'])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(409) from None
        if receipt != expected:
            raise HTTPException(409)
        diagnosis = await acknowledged_diagnosis(tx, case_id)
        if not diagnosis or (str(diagnosis['assessment_id']),diagnosis['revision']) != (saved['assessment_id'],saved['assessment_revision']):
            raise HTTPException(409)
        if saved.get('request_revision') != await submitted_revision(
                tx, request_id, row['buyer_id'], row['organization_id'], UUID(saved['watch_id'])):
            raise HTTPException(409)
        if not await retained_scope_submission(tx, case_id):
            raise HTTPException(409)
        assessed = decoded(diagnosis['body'])
        quote, decision = await current_quote(request, saved['quote_id'], {
            'source_id': saved['case_id'], 'source_revision': diagnosis['revision'],
            'assessment_id': saved['assessment_id'], 'assessment_revision': saved['assessment_revision'],
            'revision': saved['quote_revision'], 'organization_id': str(row['organization_id']),
            'buyer_id': str(row['buyer_id']),
        }, organization=actor.actor.organization_id)
        if (quote.get('policy', {}).get('revision') != saved['policy_revision']
                or quote.get('diagnosis') != assessed['diagnosis']
                or not matching_assessed_lines(saved['lines'], assessed['lines'])
                or quote.get('lines') != saved['lines']
                or decision.get('selected_line_ids') != saved['accepted_line_ids']):
            raise HTTPException(409)
        scope = published_scope(saved)
        try:
            payable = accepted_payable(quote, scope.accepted_total())
        except (KeyError, TypeError, ValueError):
            raise HTTPException(409) from None
        if 'payable_minor' in saved and (
                type(saved['payable_minor']) is not int or saved['payable_minor'] != payable):
            raise HTTPException(409)
        assessment = None
        if repair_order_id is None:
            try:
                assessment = await current_commitment(request, UUID(assessed['order_id']))
            except (ConnectionError, TimeoutError):
                raise HTTPException(503) from None
        if repair_order_id is not None or (assessment is not None and not assessment.current):
            if actor.actor.organization_id is not None:
                require_scope(actor, 'orders.read', row['organization_id'])
            if repair_order_id is None:
                repair_order_id = await repair_commitment_order(request, UUID(saved['watch_id']))
        if repair_order_id is None:
            await current_source(request, tx, assessed, commitment=assessment)
        else:
            await paid_source(request, tx, assessed, saved, repair_order_id, payable, assessment=assessment)
    return scope
