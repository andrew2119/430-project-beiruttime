"""Transactional primitives for the sole Orders journal; no independent balances."""

import asyncio
import hashlib
import json
from datetime import timedelta

from pydantic import ValidationError

from bt_contracts.orders.journal.v2 import AcceptedMoney, failed_charge_minor
from bt_contracts.orders.journal.v3 import CurrentAuthority, MovementCallback, MovementResult, ReleaseAmounts
from bt_contracts.orders.payments.signatures import verify_payload
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from service_app.orders_kernel import decoded, lock_order


def deny(code, status=409):
    raise PublicError(code, 'Reload the current payment record. أعد تحميل سجل الدفع الحالي.', status=status)


async def authority(tx, request, reader, producer):
    if reader is None or producer not in {'trust', 'service-operations'}:
        deny('money_policy_unavailable', 503)
    try:
        async with asyncio.timeout(2):
            current = CurrentAuthority.model_validate(await reader(tx, request, producer))
    except (TimeoutError, ConnectionError, ValidationError, TypeError):
        deny('money_policy_unavailable', 503)
    now = await tx.fetchval('SELECT clock_timestamp()')
    if current.request != request or not current.permitted:
        deny('money_permission_denied', 403)
    if (current.money.order_kind == 'sale') != (producer == 'trust'):
        deny('money_producer_denied', 403)
    if now >= current.valid_until:
        deny('money_policy_stale')
    return current, now


def result(row):
    return MovementResult(operation_id=row['id'], order_id=row['order_id'], state=row['state'],
                          revision=row['revision'], amount_minor=row['amount_minor'],
                          release_amounts=decoded(row['request']).get('release_amounts'),
                          recognized_fee_minor=row.get('recognized_fee_minor', 0),
                          journal_group_id=row['id'] if row['state'] == 'confirmed' else None,
                          next_actor=row['next_actor'], next_review_at=row['next_review_at']).model_dump(mode='json')


async def original(tx, request):
    row = await tx.fetchrow('SELECT * FROM l13_money_operations WHERE id=$1', request.operation_id)
    if row and decoded(row['request']) != request.model_dump(mode='json'):
        deny('money_operation_conflict')
    return row


async def lookup(tx, request, reader=None, producer=None):
    """Private recovery always rechecks current scope, even for a final receipt."""
    await lock_order(tx, request.order_id)
    await authority(tx, request, reader, producer)
    row = await original(tx, request)
    if row is None:
        deny('money_operation_unknown', 404)
    value = result(row)
    if await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id):
        value['pending_reason'] = 'reconciliation_required'
    return value


def validate(order, request, current, now):
    money = current.money
    if order['revision'] != request.expected_revision:
        deny('stale_revision')
    if (order['watch_id'] != request.watch_id or order['quote_id'] != request.quote_id
            or order['currency'] != 'USD' or order['total_minor'] != money.payable_minor
            or order.get('order_kind', 'sale') != money.order_kind):
        deny('money_order_binding_mismatch')
    if request.kind in {'refund', 'release'}:
        if order['state'] != 'paid_held':
            deny('payment_required')
        expected = order['buyer_id'] if request.kind == 'refund' else order['organization_id'] or order['seller_id']
        if (request.recipient_id != expected or request.destination.owner_id != expected
                or request.destination.organization_id != (None if request.kind == 'refund' else order['organization_id'])):
            deny('money_recipient_mismatch')
    if request.kind == 'refund':
        if not request.amount_minor <= min(current.permitted_refund_minor, money.refundable_max_minor):
            deny('refund_limit')
    elif request.kind == 'release':
        if request.release_amounts.transfer_minor == 0:
            if not current.charges_ready or current.hold:
                deny('release_prerequisites_required')
        elif (not current.release_ready or current.hold or current.received_at is None
                or current.window_ends_at is None or current.received_at > now or now < current.window_ends_at):
            deny('release_prerequisites_required')
    else:
        method = request.method
        if (method.payer_id != order['seller_id'] or method.organization_id != order['organization_id']
                or request.recipient_id != method.payer_id):
            deny('collection_payer_mismatch')
        if request.kind == 'failed_authentication':
            if not current.private_sale or not current.inspection_failed or money.order_kind != 'sale':
                deny('actual_failed_inspection_required')
            try:
                amount = failed_charge_minor(money)
            except ValueError:
                deny('accepted_return_line_required')
        else:
            if money.order_kind == 'sale':
                deny('job_required')
            amount = money.seller_commission_minor
        if request.amount_minor != amount or current.fee_already_collected:
            deny('collection_amount_or_fee_conflict')


async def reserve(tx, request, reader=None, request_id='money-reserve', producer=None):
    """Caller owns transaction. The policy reader serializes all current source facts."""
    order = await lock_order(tx, request.order_id)
    current, now = await authority(tx, request, reader, producer)
    prior = await original(tx, request)
    if prior:
        value = result(prior)
        if await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id):
            value['pending_reason'] = 'reconciliation_required'
        return value
    if await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id):
        deny('money_reconciliation_required')
    validate(order, request, current, now)
    retained = await tx.fetchrow('SELECT * FROM l13_order_quotes WHERE order_id=$1', request.order_id)
    if not retained or retained['quote_revision'] != request.quote_revision:
        deny('retained_quote_required')
    snapshot = decoded(retained['snapshot'])
    money = current.money
    if any(snapshot.get(key) != value for key, value in money.model_dump().items()
           if key not in {'order_kind', 'refundable_max_minor'}):
        deny('retained_money_mismatch')
    if request.kind == 'refund':
        payment = await tx.fetchrow(
            '''SELECT a.id,a.route FROM l13_journal_groups g JOIN l13_payment_attempts a ON a.id=g.attempt_id
            WHERE g.order_id=$1 AND a.state='confirmed' ''', request.order_id)
        if (not payment or payment['id'] != request.original_payment_attempt_id
                or payment['route'] != request.destination.route):
            deny('refund_original_payment_required')
    rows = await tx.fetch("SELECT * FROM l13_money_operations WHERE order_id=$1 AND state<>'declined'", request.order_id)
    principal = sum(row['amount_minor'] for row in rows if row['kind'] == 'refund')
    recognized = sum(row.get('recognized_fee_minor', 0) for row in rows if row['kind'] == 'refund')
    buyer_fee = money.buyer_fee_minor - recognized
    release = next((row for row in rows if row['kind'] == 'release'), None)
    fee_collection = any(row['kind'] in {'failed_authentication', 'job_fee'} for row in rows)
    if request.kind == 'refund':
        if release or principal + request.amount_minor > min(current.permitted_refund_minor, money.refundable_max_minor):
            deny('refund_limit')
    elif request.kind == 'release':
        if release or any(row['kind'] == 'refund' and row['state'] == 'pending' for row in rows):
            deny('money_reconciliation_required')
        # A collection in flight cannot also be deducted from a payout.
        if any(row['kind'] in {'failed_authentication', 'job_fee'} and row['state'] == 'pending' for row in rows):
            deny('money_reconciliation_required')
        if request.amount_minor != money.payable_minor - principal - recognized:
            deny('release_amount_mismatch')
    elif fee_collection or release:
        deny('fee_already_reserved')
    fee = money.seller_commission_minor
    if request.kind == 'release':
        collected = any(row['kind'] in {'failed_authentication', 'job_fee'} and row['state'] == 'confirmed' for row in rows)
        if current.fee_already_collected != collected:
            deny('fee_collection_binding_mismatch')
        if collected:
            fee = 0
    if request.kind == 'release' and request.amount_minor < fee + buyer_fee + money.shipping_minor + money.tax_minor:
        deny('fee_collection_required')
    if request.kind == 'release':
        if request.release_amounts.transfer_minor == 0 and (principal != money.refundable_max_minor or fee or buyer_fee):
            deny('release_prerequisites_required')
        deductions = fee + buyer_fee + money.shipping_minor + money.tax_minor
        expected = ReleaseAmounts(gross_minor=request.amount_minor, business_fee_minor=fee,
            buyer_fee_minor=buyer_fee, shipping_minor=money.shipping_minor,
            tax_minor=money.tax_minor, transfer_minor=request.amount_minor - deductions)
        if request.release_amounts != expected:
            deny('release_amounts_mismatch')
    row = await tx.fetchrow(
        '''INSERT INTO l13_money_operations(id,order_id,kind,request,money,amount_minor,fee_minor,next_actor,next_review_at)
        VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,$9) RETURNING *''',
        request.operation_id, request.order_id, request.kind, request.model_dump_json(), money.model_dump_json(),
        request.amount_minor, fee, current.responsible_actor_id, now + timedelta(hours=24))
    await tx.execute('UPDATE l08_orders SET financial_revision=financial_revision+1 WHERE id=$1', request.order_id)
    await emit(tx, row, 'requested', request_id)
    return result(row)


def entries(row):
    amount, fee = row['amount_minor'], row['fee_minor']
    if row['kind'] == 'refund':
        recognized = row.get('recognized_fee_minor', 0)
        return [(account, value) for account, value in [('buyer_held', amount + recognized),
                ('simulated_clearing', -amount), ('fee_income', -recognized)] if value]
    if row['kind'] in {'failed_authentication', 'job_fee'}:
        return [(account, value) for account, value in [('simulated_clearing', amount),
                ('fee_income', -fee), ('transport_payable', -(amount - fee))] if value]
    breakdown = ReleaseAmounts.model_validate(decoded(row['request'])['release_amounts'])
    return [(account, value) for account, value in [('buyer_held', amount),
            ('simulated_clearing', -breakdown.transfer_minor),
            ('fee_income', -(breakdown.business_fee_minor + breakdown.buyer_fee_minor)),
            ('transport_payable', -breakdown.shipping_minor), ('tax_payable', -breakdown.tax_minor)] if value]


async def emit(tx, row, state, request_id):
    await enqueue(tx, EventEnvelope(type='orders.money-' + state + '.v3', source='orders',
        subject=str(row['order_id']), request_id=request_id,
        data={'operation_id': str(row['id']), 'order_id': str(row['order_id']), 'kind': row['kind'],
              'state': row['state'], 'revision': row['revision'], 'simulated': True}),
        ['communications-order-timeline'])


async def settle(tx, raw, signature, request_id='money-result'):
    """Verify exact signed bytes before any lookup; no caller-supplied policy result."""
    callback = verify_payload(raw, signature, MovementCallback)
    request = callback.request
    # Global callback serialization precedes aggregate locking, as in checkout.
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'l13-money-event:' + str(callback.event_id))
    await lock_order(tx, request.order_id)
    row = await original(tx, request)
    if row is None:
        deny('money_operation_unknown', 404)
    digest = hashlib.sha256(callback.model_dump_json().encode()).hexdigest()
    prior = await tx.fetchrow('SELECT * FROM l13_money_callbacks WHERE event_id=$1', callback.event_id)
    if prior:
        if prior['digest'] != digest:
            deny('money_callback_conflict')
        value = decoded(prior['result'])
        if await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id):
            value['pending_reason'] = 'reconciliation_required'
        return value
    conflicting = row['state'] == 'declined' and (
        callback.outcome == 'confirmed'
        or (callback.outcome == 'pending' and callback.sequence > row['sequence']))
    if conflicting and not await tx.fetchval(
            'SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id):
        # Preserve the final receipt while holding conflicting or uncertain money.
        await tx.execute(
            '''INSERT INTO l13_money_reconciliations(event_id,operation_id,order_id,next_actor)
            VALUES($1,$2,$3,$4)''', callback.event_id, row['id'], row['order_id'], row['next_actor'])
        await tx.execute('UPDATE l08_orders SET financial_revision=financial_revision+1 WHERE id=$1', request.order_id)
        await emit(tx, row, 'reconciliation', request_id)
    if row['state'] not in {'confirmed', 'declined'} and callback.sequence > row['sequence']:
        recognized = 0
        if request.kind == 'refund' and callback.outcome == 'confirmed':
            money = AcceptedMoney.model_validate(decoded(row['money']))
            refunded = await tx.fetchval(
                "SELECT COALESCE(sum(amount_minor),0) FROM l13_money_operations WHERE order_id=$1 AND kind='refund' AND state='confirmed'", request.order_id)
            if refunded + row['amount_minor'] == money.refundable_max_minor:
                recognized = money.buyer_fee_minor
        row = await tx.fetchrow(
            '''UPDATE l13_money_operations SET state=$2,sequence=$3,revision=revision+1,recognized_fee_minor=$4
            WHERE id=$1 RETURNING *''', request.operation_id, callback.outcome, callback.sequence, recognized)
        if callback.outcome == 'confirmed':
            await tx.execute(
                '''INSERT INTO l13_journal_postings(id,order_id,movement_id,currency,total_minor)
                VALUES($1,$2,$1,'USD',$3)''', row['id'], row['order_id'], row['amount_minor'])
            await tx.executemany('INSERT INTO l13_journal_entries(group_id,account,amount_minor) VALUES($1,$2,$3)',
                                 [(row['id'], account, amount) for account, amount in entries(row)])
        await tx.execute('UPDATE l08_orders SET financial_revision=financial_revision+1 WHERE id=$1', request.order_id)
        await emit(tx, row, callback.outcome, request_id)
    value = result(row)
    if await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id):
        value['pending_reason'] = 'reconciliation_required'
    await tx.execute('INSERT INTO l13_money_callbacks(event_id,operation_id,digest,result) VALUES($1,$2,$3,$4::jsonb)',
                     callback.event_id, row['id'], digest, json.dumps(value))
    return value


async def failed_return_status(tx, request, reader=None, producer=None):
    """Custody/publication consume this current result, never a cached paid flag."""
    await lock_order(tx, request.order_id)
    current, _ = await authority(tx, request, reader, producer)
    row = await original(tx, request)
    if request.kind != 'failed_authentication' or not current.inspection_failed or not current.private_sale:
        deny('actual_failed_inspection_required')
    review = await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', request.order_id)
    confirmed = row is not None and row['state'] == 'confirmed' and not review
    return {'return_allowed': confirmed and current.custody_instruction_id is not None,
            'publication_restricted': not confirmed, 'buyer_refund_blocked': False,
            'collection_state': row['state'] if row else 'unavailable'}


async def financial_readiness(tx, order_id):
    """Read under the order lock so pending allocations and receipts share one revision."""
    order = await lock_order(tx, order_id)
    if order['currency'] != 'USD':
        deny('legacy_currency_reconciliation_required')
    rows = await tx.fetch("SELECT * FROM l13_money_operations WHERE order_id=$1 AND state<>'declined'", order_id)
    review = bool(await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', order_id))
    outgoing = [row for row in rows if row['kind'] in {'refund', 'release'}]
    reserved = sum(row['amount_minor'] for row in outgoing if row['state'] == 'pending')
    moved = sum(row['amount_minor'] + row.get('recognized_fee_minor', 0)
                for row in outgoing if row['state'] == 'confirmed')
    held = max(0, order['total_minor'] - moved) if order['state'] == 'paid_held' else 0
    ready = order['state'] == 'paid_held' and not outgoing and not review
    return {'schema_version': 3, 'order_id': str(order_id), 'revision': order['revision'] + order.get('financial_revision', 0),
            'state': 'paid_held' if ready else 'pending' if held or reserved or review or order['state'] in {'payment_unknown', 'expired_fenced'} else 'unpaid',
            'held_minor': held, 'reserved_minor': reserved, 'currency': 'USD',
            'movement_status': ('reconciliation' if review else 'release_pending' if any(row['kind'] == 'release' and row['state'] == 'pending' for row in outgoing)
                else 'refund_pending' if any(row['kind'] == 'refund' and row['state'] == 'pending' for row in outgoing)
                else 'released' if any(row['kind'] == 'release' for row in outgoing)
                else 'refunded' if outgoing else 'none'),
            'simulated': True, 'payment_authority': False}


async def current_paid_fact(tx, order_id, *, version=1):
    from service_app.orders_kernel import paid_fact
    readiness = await financial_readiness(tx, order_id)
    if readiness['state'] != 'paid_held':
        rows = await tx.fetch("SELECT * FROM l13_money_operations WHERE order_id=$1 AND state<>'declined'", order_id)
        if any(row['kind'] in {'refund', 'release'} for row in rows) or await tx.fetchval(
                'SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', order_id):
            deny('financial_readiness_upgrade_required')
    return await paid_fact(tx, order_id, version=version)
