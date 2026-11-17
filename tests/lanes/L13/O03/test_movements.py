"""Contract and transaction-adapter cases; real database constraints remain separate."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bt_contracts_core.errors import PublicError
from pydantic import ValidationError


def economics(kind='sale'):
    return dict(order_kind=kind, currency='USD', price_minor=500000,
                buyer_fee_minor=15000 if kind == 'sale' else 0, seller_commission_minor=25000,
                seller_net_minor=475000, shipping_minor=0, tax_minor=0,
                payable_minor=515000 if kind == 'sale' else 500000,
                return_fee_minor=2000, refundable_max_minor=500000)


@pytest.fixture
def ledger(modules, monkeypatch):
    contract = modules('bt_contracts.orders.journal.v3', 'packages/contracts-orders/journal/v3.py')
    kernel = modules('o03_movements', 'services/orders/modules/journal/movements.py')
    monkeypatch.setenv('BT_SIMULATED_PAYMENT_SECRET', 'synthetic-signing-secret-for-local-proofs-only')
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    order = {key: uuid4() for key in ('id', 'watch_id', 'quote_id', 'buyer_id', 'seller_id')}
    order.update(revision=3, state='paid_held', currency='USD', total_minor=515000,
                 organization_id=None, order_kind='sale')
    destination_id, payment_id = uuid4(), uuid4()
    destination = dict(id=destination_id, owner_id=order['buyer_id'], organization_id=None, revision=1, route='card', reference='SIM-RECIPIENT-' + str(destination_id))
    request = contract.Movement(operation_id=uuid4(), order_id=order['id'], watch_id=order['watch_id'],
        actor_id=order['buyer_id'], organization_id=None, expected_revision=3,
        quote_id=order['quote_id'], quote_revision=2, source_id=uuid4(), source_revision=1,
        kind='refund', amount_minor=500000, recipient_id=order['buyer_id'], destination=destination, original_payment_attempt_id=payment_id)
    current = contract.CurrentAuthority(request=request, money=economics(), valid_until=now + timedelta(minutes=1),
        permitted=True, responsible_actor_id=uuid4(), permitted_refund_minor=500000,
        private_sale=True, inspection_failed=True, release_ready=True, hold=False,
        received_at=now - timedelta(days=4), window_ends_at=now)
    state = dict(operations={}, callbacks={}, postings=[], entries=[], events=[], reads=0,
                 reconciliations=[], snapshot={key: value for key, value in economics().items() if key not in {'order_kind', 'refundable_max_minor'}})

    async def reader(tx, command, producer):
        state['producer'] = producer
        state['reads'] += 1
        return current.model_copy(update={'request': command})

    async def fetchrow(sql, *args):
        if sql.startswith('SELECT * FROM l08_orders'):
            assert 'FOR UPDATE' in sql
            return order
        if sql.startswith('SELECT * FROM l13_money_operations'):
            return state['operations'].get(args[0])
        if sql.startswith('SELECT * FROM l13_money_callbacks'):
            return state['callbacks'].get(args[0])
        if sql.lstrip().startswith('SELECT a.id,a.route'):
            return {'id': payment_id, 'route': 'card'}
        if sql.startswith('SELECT * FROM l13_order_quotes'):
            return {'quote_revision': 2, 'snapshot': state['snapshot']}
        if sql.lstrip().startswith('INSERT INTO l13_money_operations'):
            row = dict(zip(('id', 'order_id', 'kind', 'request', 'money', 'amount_minor', 'fee_minor', 'next_actor', 'next_review_at'), args))
            row.update(state='pending', revision=1, sequence=0)
            state['operations'][args[0]] = row
            return row
        if sql.lstrip().startswith('UPDATE l13_money_operations'):
            row = state['operations'][args[0]]
            row.update(state=args[1], sequence=args[2], revision=row['revision'] + 1, recognized_fee_minor=args[3])
            return row
        raise AssertionError(sql)

    async def execute(sql, *args):
        if sql.startswith('UPDATE l08_orders SET financial_revision'):
            order['financial_revision'] = order.get('financial_revision', 0) + 1
            return
        if 'pg_advisory_xact_lock' in sql:
            return
        if 'INSERT INTO l13_journal_postings' in sql:
            state['postings'].append(args)
        elif 'INSERT INTO l13_money_callbacks' in sql:
            state['callbacks'][args[0]] = {'digest': args[2], 'result': json.loads(args[3])}
        elif 'INSERT INTO l13_money_reconciliations' in sql:
            state['reconciliations'].append(args)
        else:
            raise AssertionError(sql)

    async def fetchval(sql, *args):
        if sql.startswith('SELECT operator_id FROM l13_payment_recovery_assignments'):
            return state.get('operator_id', current.responsible_actor_id)
        if sql.startswith('SELECT COALESCE(sum(amount_minor),0)'):
            return sum(row['amount_minor'] for row in state['operations'].values() if row['kind'] == 'refund' and row['state'] == 'confirmed')
        if sql == 'SELECT clock_timestamp()':
            return now
        if sql.startswith('SELECT 1 FROM l13_money_reconciliations'):
            return bool(state['reconciliations'])
        raise AssertionError(sql)

    async def fetch(sql, *args):
        return [row for row in state['operations'].values() if row['state'] != 'declined']

    async def executemany(sql, rows):
        state['entries'].extend(rows)

    async def enqueue(tx, event, destinations):
        state['events'].append(event)

    monkeypatch.setattr(kernel, 'enqueue', enqueue)
    tx = SimpleNamespace(fetchrow=fetchrow, fetchval=fetchval, execute=execute, fetch=fetch, executemany=executemany)
    return SimpleNamespace(contract=contract, kernel=kernel, now=now, order=order, request=request,
                           current=current, state=state, reader=reader, tx=tx)


async def reserve(case, request=None):
    request = request or case.request
    if request.kind == 'release' and request.release_amounts is None:
        money = case.current.money
        fee = 0 if case.current.fee_already_collected else money.seller_commission_minor
        request.release_amounts = case.contract.ReleaseAmounts(gross_minor=request.amount_minor,
            business_fee_minor=fee, buyer_fee_minor=money.buyer_fee_minor,
            shipping_minor=money.shipping_minor, tax_minor=money.tax_minor,
            transfer_minor=request.amount_minor - fee - money.buyer_fee_minor - money.shipping_minor - money.tax_minor)
    return await case.kernel.reserve(case.tx, request or case.request, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations')


async def deliver(case, request=None, **changes):
    from bt_contracts.orders.payments.signatures import sign
    body = case.contract.MovementCallback(event_id=uuid4(), request=request or case.request,
        **({'outcome': 'confirmed', 'sequence': 1} | changes))
    raw = body.model_dump_json().encode()
    return await case.kernel.settle(case.tx, raw, sign(raw)), raw


@pytest.mark.asyncio
async def test_reserve_lost_response_restart_lookup_and_once_only_balanced_refund(ledger):
    case = ledger
    first = await reserve(case)
    assert first['state'] == 'pending' and not case.state['postings']
    assert await reserve(case) == first
    assert await case.kernel.lookup(case.tx, case.request, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations') == first
    confirmed, raw = await deliver(case)
    from bt_contracts.orders.payments.signatures import sign
    assert await case.kernel.settle(case.tx, raw, sign(raw)) == confirmed
    assert (await deliver(case, sequence=99, outcome='declined'))[0] == confirmed
    assert len(case.state['postings']) == 1
    assert sum(row[2] for row in case.state['entries']) == 0
    assert {row[2] for row in case.state['entries']} == {515000, -500000, -15000}
    assert len(case.state['events']) == 2


@pytest.mark.asyncio
async def test_unknown_refunds_reserve_same_cap_and_decline_frees_it(ledger):
    case = ledger
    await reserve(case)
    second = case.request.model_copy(update={'operation_id': uuid4(), 'amount_minor': 1})
    with pytest.raises(PublicError, match='refund_limit'):
        await reserve(case, second)
    await deliver(case, outcome='pending')
    with pytest.raises(PublicError, match='refund_limit'):
        await reserve(case, second)
    await deliver(case, outcome='declined', sequence=2)
    assert (await reserve(case, second))['state'] == 'pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,allowed', [(-1, False), (0, False), (1, True)])
async def test_policy_validity_before_equal_after(ledger, offset, allowed):
    case = ledger
    case.current.valid_until = case.now + timedelta(seconds=offset)
    if allowed:
        await reserve(case)
    else:
        with pytest.raises(PublicError, match='money_policy_stale'):
            await reserve(case)
        assert not case.state['operations']


@pytest.mark.asyncio
async def test_revoked_cross_scope_conflicting_and_stale_requests(ledger):
    case = ledger
    with pytest.raises(PublicError, match='stale_revision'):
        await reserve(case, case.request.model_copy(update={'expected_revision': 2}))
    with pytest.raises(PublicError, match='money_recipient_mismatch'):
        await reserve(case, case.request.model_copy(update={'recipient_id': uuid4()}))
    await reserve(case)
    with pytest.raises(PublicError, match='money_operation_conflict'):
        await reserve(case, case.request.model_copy(update={'amount_minor': 1}))
    case.current.permitted = False
    with pytest.raises(PublicError, match='money_permission_denied'):
        await case.kernel.lookup(case.tx, case.request, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations')
    assert case.state['reads'] == 5


@pytest.mark.asyncio
async def test_missing_and_timed_out_policy_never_reserves(ledger):
    case = ledger
    with pytest.raises(PublicError, match='money_policy_unavailable'):
        await case.kernel.reserve(case.tx, case.request)

    async def timeout(tx, request, producer):
        raise TimeoutError

    with pytest.raises(PublicError, match='money_policy_unavailable'):
        await case.kernel.reserve(case.tx, case.request, timeout, producer='trust')
    assert not case.state['operations']


def collection(case, kind='failed_authentication'):
    method_id = uuid4()
    method = dict(id=method_id, payer_id=case.order['seller_id'], organization_id=case.order['organization_id'],
                  route='card', reference='SIM-METHOD-' + str(method_id))
    return case.contract.Movement.model_validate(case.request.model_dump() | dict(operation_id=uuid4(), kind=kind,
        recipient_id=case.order['seller_id'], method=method, destination=None, original_payment_attempt_id=None, amount_minor=27000 if kind == 'failed_authentication' else 25000))


@pytest.mark.asyncio
async def test_unknown_seller_charge_blocks_return_not_buyer_refund(ledger):
    case = ledger
    charge = collection(case)
    await reserve(case, charge)
    status = await case.kernel.failed_return_status(case.tx, charge, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations')
    assert status == dict(return_allowed=False, publication_restricted=True, buyer_refund_blocked=False, collection_state='pending')
    assert (await reserve(case))['amount_minor'] == 500000
    await deliver(case, charge)
    assert not (await case.kernel.failed_return_status(case.tx, charge, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations'))['return_allowed']
    case.current.custody_instruction_id = uuid4()
    assert (await case.kernel.failed_return_status(case.tx, charge, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations'))['return_allowed']
    with pytest.raises(PublicError, match='fee_already_reserved'):
        await reserve(case, collection(case))
    assert sum(row[2] for row in case.state['entries']) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['service_job', 'customization_job'])
async def test_full_job_refund_is_gross_and_business_fee_collected_separately_once(ledger, kind):
    case = ledger
    money = economics(kind)
    case.current.money = case.current.money.model_validate(money)
    case.order.update(order_kind=kind, total_minor=500000)
    case.state['snapshot'] = {key: value for key, value in money.items() if key not in {'order_kind', 'refundable_max_minor'}}
    await reserve(case)
    refunded, _ = await deliver(case)
    assert refunded['amount_minor'] == 500000
    charge = collection(case, 'job_fee')
    await reserve(case, charge)
    assert len(case.state['postings']) == 1
    await deliver(case, charge)
    assert len(case.state['postings']) == 2
    assert [row[2] for row in case.state['entries'] if row[1] == 'simulated_clearing'] == [-500000, 25000]
    with pytest.raises(PublicError, match='fee_already_reserved'):
        await reserve(case, collection(case, 'job_fee'))


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, True), (1, False)])
async def test_release_receipt_window_boundary(ledger, offset, allowed):
    case = ledger
    release = case.request.model_copy(update={'kind': 'release', 'amount_minor': 515000, 'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None, 'destination': case.request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    case.current.window_ends_at = case.now + timedelta(seconds=offset)
    if not allowed:
        with pytest.raises(PublicError, match='release_prerequisites_required'):
            await reserve(case, release)
    else:
        await reserve(case, release)
        await deliver(case, release)
        assert sum(row[2] for row in case.state['entries']) == 0
        assert {row[1]: row[2] for row in case.state['entries']} == {'buyer_held': 515000, 'simulated_clearing': -475000, 'fee_income': -40000}
        with pytest.raises(PublicError, match='refund_limit'):
            await reserve(case, case.request.model_copy(update={'operation_id': uuid4()}))


@pytest.mark.asyncio
async def test_held_or_unreceived_release_and_wrong_retained_money_deny(ledger):
    case = ledger
    release = case.request.model_copy(update={'kind': 'release', 'amount_minor': 515000, 'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None, 'destination': case.request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    case.current.hold = True
    with pytest.raises(PublicError, match='release_prerequisites_required'):
        await reserve(case, release)
    case.current.hold = False
    case.current.received_at = None
    with pytest.raises(PublicError, match='release_prerequisites_required'):
        await reserve(case, release)
    case.state['snapshot']['price_minor'] = 1
    with pytest.raises(PublicError, match='retained_money_mismatch'):
        await reserve(case)


@pytest.mark.asyncio
async def test_forged_or_changed_signed_callbacks_and_reordering(ledger):
    case = ledger
    await reserve(case)
    _, raw = await deliver(case, outcome='pending', sequence=2)
    from bt_contracts.orders.payments.signatures import sign
    with pytest.raises(PublicError, match='signature_invalid'):
        await case.kernel.settle(case.tx, raw, '0' * 64)
    assert (await deliver(case, sequence=1))[0]['state'] == 'pending'
    changed = case.contract.MovementCallback.model_validate_json(raw)
    changed.outcome = 'confirmed'
    wire = changed.model_dump_json().encode()
    with pytest.raises(PublicError, match='money_callback_conflict'):
        await case.kernel.settle(case.tx, wire, sign(wire))
    changed.event_id = uuid4()
    changed.request.amount_minor = 1
    wire = changed.model_dump_json().encode()
    with pytest.raises(PublicError, match='money_operation_conflict'):
        await case.kernel.settle(case.tx, wire, sign(wire))
    assert not case.state['postings']


@pytest.mark.parametrize('value', [True, 1.5, '500000', -1, 18000000000001])
def test_money_uses_bounded_integer_cents(ledger, value):
    with pytest.raises(ValidationError):
        ledger.contract.Movement.model_validate(ledger.request.model_dump() | {'amount_minor': value})


@pytest.mark.asyncio
async def test_partial_decision_cap_counts_all_pending_and_confirmed_requests(ledger):
    case = ledger
    case.current.permitted_refund_minor = 100000
    partial = case.request.model_copy(update={'amount_minor': 100000})
    await reserve(case, partial)
    await deliver(case, partial)
    with pytest.raises(PublicError, match='refund_limit'):
        await reserve(case, partial.model_copy(update={'operation_id': uuid4()}))


@pytest.mark.asyncio
@pytest.mark.parametrize('collected', [False, True])
async def test_release_fee_flag_must_match_this_journal(ledger, collected):
    case = ledger
    if collected:
        charge = collection(case)
        await reserve(case, charge)
        await deliver(case, charge)
    case.current.fee_already_collected = not collected
    release = case.request.model_copy(update={'operation_id': uuid4(), 'kind': 'release',
        'amount_minor': 515000, 'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None, 'destination': case.request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    with pytest.raises(PublicError, match='fee_collection_binding_mismatch'):
        await reserve(case, release)
    case.current.fee_already_collected = collected
    release.release_amounts = None
    await reserve(case, release)
    await deliver(case, release)
    release_entries = [row for row in case.state['entries'] if row[0] == release.operation_id]
    assert {row[1]: row[2] for row in release_entries}['fee_income'] == (-15000 if collected else -40000)


@pytest.mark.asyncio
async def test_late_conflicting_refund_is_durable_review_and_blocks_new_money(ledger):
    case = ledger
    await reserve(case)
    await deliver(case, outcome='declined')
    value, raw = await deliver(case, sequence=2)
    assert value['state'] == 'declined' and value['pending_reason'] == 'reconciliation_required'
    assert not case.state['postings'] and len(case.state['reconciliations']) == 1
    from bt_contracts.orders.payments.signatures import sign
    assert await case.kernel.settle(case.tx, raw, sign(raw)) == value
    assert (await case.kernel.lookup(case.tx, case.request, case.reader, producer='trust' if case.order['order_kind'] == 'sale' else 'service-operations'))['pending_reason'] == 'reconciliation_required'
    with pytest.raises(PublicError, match='money_reconciliation_required'):
        await reserve(case, case.request.model_copy(update={'operation_id': uuid4()}))


@pytest.mark.asyncio
async def test_non_ascii_signature_and_stream_bound(ledger):
    from bt_contracts.orders.payments.signatures import callback_bytes
    case = ledger
    with pytest.raises(PublicError, match='signature_invalid'):
        await case.kernel.settle(case.tx, b'{}', 'ع' * 64)

    async def chunks():
        yield b'a' * 8192
        yield b'b'
        raise AssertionError('The bounded reader must stop')

    with pytest.raises(PublicError, match='callback_too_large'):
        await callback_bytes(SimpleNamespace(stream=chunks))


def test_deterministic_examples_parse_as_the_published_contract(ledger):
    from pathlib import Path
    fixture = json.loads((Path(__file__).resolve().parents[4] /
        'packages/contracts-orders/journal/fixtures/movements-v3.json').read_text())
    contract = ledger.contract
    request = contract.Movement.model_validate(fixture['request'])
    proof = contract.CurrentAuthority.model_validate(fixture['authority'])
    assert proof.request == request
    assert {case['case'] for case in fixture['cases']} == {'success', 'denied', 'stale', 'lost_response'}
    for example in fixture['cases']:
        contract.Movement.model_validate(fixture['request'] | example['request_changes'])


@pytest.mark.asyncio
async def test_refund_original_route_and_immutable_destination(ledger):
    case = ledger
    wrong_attempt = case.request.model_copy(update={'original_payment_attempt_id': uuid4()})
    with pytest.raises(PublicError, match='refund_original_payment_required'):
        await reserve(case, wrong_attempt)
    wrong_route = case.request.model_copy(update={'destination': case.request.destination.model_copy(update={'route': 'omt'})})
    with pytest.raises(PublicError, match='refund_original_payment_required'):
        await reserve(case, wrong_route)
    await reserve(case)
    redirected = case.request.model_copy(update={'destination': case.request.destination.model_copy(update={'revision': 2})})
    with pytest.raises(PublicError, match='money_operation_conflict'):
        await reserve(case, redirected)


@pytest.mark.asyncio
async def test_pending_refund_prevents_release_and_pending_collection_prevents_fee_deduction(ledger):
    case = ledger
    await reserve(case, case.request.model_copy(update={'amount_minor': 100000}))
    release = case.request.model_copy(update={'operation_id': uuid4(), 'kind': 'release', 'amount_minor': 415000,
        'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None,
        'destination': case.request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    with pytest.raises(PublicError, match='money_reconciliation_required'):
        await reserve(case, release)
    await deliver(case, case.request.model_copy(update={'amount_minor': 100000}), outcome='declined')
    await reserve(case, collection(case))
    release.amount_minor = 515000
    with pytest.raises(PublicError, match='money_reconciliation_required'):
        await reserve(case, release)


@pytest.mark.asyncio
async def test_authenticated_producer_scope_is_passed_and_enforced(ledger):
    case = ledger
    with pytest.raises(PublicError, match='money_producer_denied'):
        await case.kernel.reserve(case.tx, case.request, case.reader, producer='service-operations')
    assert case.state['producer'] == 'service-operations'
    assert not case.state['operations']
    with pytest.raises(PublicError, match='money_policy_unavailable'):
        await case.kernel.reserve(case.tx, case.request, case.reader)


@pytest.mark.asyncio
async def test_same_operation_retry_keeps_durable_reconciliation_reason(ledger):
    case = ledger
    await reserve(case)
    await deliver(case, outcome='declined')
    await deliver(case, sequence=2)
    assert (await reserve(case))['pending_reason'] == 'reconciliation_required'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,gross,fee', [('sale', 515000, 40000), ('service_job', 500000, 25000), ('customization_job', 500000, 25000)])
async def test_signed_release_binds_gross_deductions_and_actual_transfer(ledger, kind, gross, fee):
    case = ledger
    money = economics(kind)
    case.current.money = case.current.money.model_validate(money)
    case.order.update(order_kind=kind, total_minor=gross)
    case.state['snapshot'] = {key: value for key, value in money.items() if key not in {'order_kind', 'refundable_max_minor'}}
    release = case.request.model_copy(update={'kind': 'release', 'amount_minor': gross,
        'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None,
        'destination': case.request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    reserved = await reserve(case, release)
    assert reserved['release_amounts']['gross_minor'] == gross
    assert reserved['release_amounts']['transfer_minor'] == gross - fee
    wrong = release.release_amounts.model_copy(update={'business_fee_minor': 24999,
        'transfer_minor': gross - fee + 1})
    release.release_amounts = wrong
    from bt_contracts.orders.payments.signatures import sign
    callback = case.contract.MovementCallback(event_id=uuid4(), request=release, outcome='confirmed', sequence=1)
    raw = callback.model_dump_json().encode()
    with pytest.raises(PublicError, match='money_operation_conflict'):
        await case.kernel.settle(case.tx, raw, sign(raw))
    release.release_amounts = case.contract.ReleaseAmounts.model_validate(reserved['release_amounts'])
    confirmed, _ = await deliver(case, release)
    assert confirmed['release_amounts'] == reserved['release_amounts']
    assert next(row[2] for row in case.state['entries'] if row[1] == 'simulated_clearing') == -(gross - fee)
    assert sum(row[2] for row in case.state['entries']) == 0
    release.operation_id = uuid4()
    release.release_amounts = wrong
    case.state['operations'].clear()
    with pytest.raises(PublicError, match='release_amounts_mismatch'):
        await reserve(case, release)


@pytest.mark.asyncio
async def test_every_callback_including_old_receipt_preserves_unresolved_review(ledger):
    case = ledger
    await reserve(case)
    _, declined_raw = await deliver(case, outcome='declined')
    await deliver(case, sequence=2)
    subsequent, raw = await deliver(case, sequence=3, outcome='pending')
    assert subsequent['state'] == 'declined'
    assert subsequent['pending_reason'] == 'reconciliation_required'
    from bt_contracts.orders.payments.signatures import sign
    for receipt in (raw, declined_raw):
        value = await case.kernel.settle(case.tx, receipt, sign(receipt))
        assert value['pending_reason'] == 'reconciliation_required'
    assert len(case.state['reconciliations']) == 1
    assert not case.state['postings']


def test_release_breakdown_is_required_and_balanced(ledger):
    case = ledger
    release = case.request.model_dump() | {'kind': 'release', 'original_payment_attempt_id': None}
    with pytest.raises(ValidationError):
        case.contract.Movement.model_validate(release)
    with pytest.raises(ValidationError):
        case.contract.ReleaseAmounts(gross_minor=515000, business_fee_minor=25000,
            buyer_fee_minor=15000, shipping_minor=0, tax_minor=0, transfer_minor=475001)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['refund', 'release'])
async def test_current_readiness_after_reserved_and_confirmed_movement(ledger, kind):
    case = ledger
    initial = await case.kernel.financial_readiness(case.tx, case.order['id'])
    assert initial['state'] == 'paid_held' and initial['held_minor'] == 515000
    request = case.request
    if kind == 'release':
        request = request.model_copy(update={'kind': 'release', 'amount_minor': 515000,
            'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None,
            'destination': request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    await reserve(case, request)
    pending = await case.kernel.financial_readiness(case.tx, case.order['id'])
    assert pending['state'] == 'pending' and pending['revision'] > initial['revision']
    assert pending['movement_status'] == kind + '_pending'
    with pytest.raises(PublicError, match='financial_readiness_upgrade_required'):
        await case.kernel.current_paid_fact(case.tx, case.order['id'], version=2)
    await deliver(case, request)
    final = await case.kernel.financial_readiness(case.tx, case.order['id'])
    assert final['held_minor'] == 0 and final['reserved_minor'] == 0
    assert final['movement_status'] == ('refunded' if kind == 'refund' else 'released')
    assert final['state'] == 'unpaid' and final['revision'] > pending['revision']
    with pytest.raises(PublicError, match='financial_readiness_upgrade_required'):
        await case.kernel.current_paid_fact(case.tx, case.order['id'])


@pytest.mark.asyncio
async def test_full_watch_refund_recognizes_buyer_fee_without_seller_transfer(ledger):
    case = ledger
    partial = case.request.model_copy(update={'amount_minor': 100000})
    await reserve(case, partial)
    await deliver(case, partial)
    final = case.request.model_copy(update={'operation_id': uuid4(), 'amount_minor': 400000})
    await reserve(case, final)
    await deliver(case, final)
    charge = collection(case)
    await reserve(case, charge)
    await deliver(case, charge)
    entries = case.state['entries']
    assert sum(row[2] for row in entries if row[1] == 'buyer_held') == 515000
    assert sum(row[2] for row in entries if row[1] == 'fee_income') == -40000
    assert sum(row[2] for row in entries) == 0
    assert len(case.state['postings']) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['service_job', 'customization_job'])
async def test_job_refund_removes_readiness_and_duplicate_keeps_revision(ledger, kind):
    case = ledger
    money = economics(kind)
    case.current.money = case.current.money.model_validate(money)
    case.order.update(order_kind=kind, total_minor=500000)
    case.state['snapshot'] = {key: value for key, value in money.items() if key not in {'order_kind', 'refundable_max_minor'}}
    await reserve(case)
    _, raw = await deliver(case)
    final = await case.kernel.financial_readiness(case.tx, case.order['id'])
    assert final['held_minor'] == 0 and final['state'] == 'unpaid'
    from bt_contracts.orders.payments.signatures import sign
    await case.kernel.settle(case.tx, raw, sign(raw))
    assert await case.kernel.financial_readiness(case.tx, case.order['id']) == final
    with pytest.raises(PublicError, match='financial_readiness_upgrade_required'):
        await case.kernel.current_paid_fact(case.tx, case.order['id'], version=2)


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [False, True])
async def test_payment_recovery_overlays_current_funds_without_rewriting_receipt(ledger, modules, changed):
    case = ledger
    processor = modules('o03_processor', 'services/orders/modules/payments/processor.py')
    receipt = {'paid': True, 'status': 'succeeded'}
    async def fetchval(sql, *args):
        assert 'l13_money_reconciliations' in sql
        return changed
    case.tx.fetchval = fetchval
    case.order['financial_revision'] = 2
    value = await processor.current_payment_result(case.tx, case.order['id'], receipt)
    assert value['paid'] is (not changed)
    assert value['payment_revision'] == 5
    assert receipt == {'paid': True, 'status': 'succeeded'}


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['payment_unknown', 'expired_fenced'])
async def test_unknown_original_payment_stays_pending(ledger, state):
    ledger.order['state'] = state
    value = await ledger.kernel.financial_readiness(ledger.tx, ledger.order['id'])
    assert value['state'] == 'pending' and value['held_minor'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('assigned', [True, False])
@pytest.mark.parametrize('outcome', ['pending', 'confirmed'])
@pytest.mark.parametrize('newer', [False, True])
@pytest.mark.parametrize('sequence', [1, 3])
async def test_late_checkout_confirmation_fences_expiry_and_current_money(ledger, modules, monkeypatch, newer, sequence, outcome, assigned):
    case = ledger
    processor = modules('o03_checkout_processor', 'services/orders/modules/payments/processor.py')
    clock = modules('o03_clock', 'services/orders/runtime/service_app/payment_clock.py')
    case.order.update(state='payment_unknown', deadline=case.now - timedelta(seconds=1))
    attempt = dict(id=uuid4(), order_id=case.order['id'], buyer_id=case.order['buyer_id'],
        quote_id=case.order['quote_id'], quote_revision=2, route='card', currency='USD',
        total_minor=515000, state='declined', sequence=2, created_at=case.now)
    attempt['reference'] = 'SIM-' + str(attempt['id'])
    from bt_contracts.orders.payments import PaymentCallback
    body = PaymentCallback(event_id=uuid4(), attempt_id=attempt['id'], outcome=outcome, sequence=sequence,
        **{k: attempt[k] for k in ('order_id','buyer_id','quote_id','quote_revision','route','reference','currency','total_minor')})
    receipts = {}
    original_fetchrow, original_execute, original_fetchval = case.tx.fetchrow, case.tx.execute, case.tx.fetchval

    async def fetchrow(sql, *args):
        if 'FROM l13_payment_callbacks' in sql:
            return receipts.get(args[0])
        if 'FROM l13_payment_attempts' in sql:
            return attempt
        if "SET state='held'" in sql:
            attempt.update(state='held', sequence=max(attempt['sequence'], args[1]))
            return attempt
        return await original_fetchrow(sql, *args)

    async def execute(sql, *args):
        if 'INSERT INTO l13_payment_callbacks' in sql:
            receipts[args[0]] = {'digest': args[2], 'outcome': json.loads(args[3])}
            return
        await original_execute(sql, *args)

    async def fetchval(sql, *args):
        if 'created_at,id' in sql:
            return newer
        if 'SELECT EXISTS' in sql:
            return bool(case.state['reconciliations'])
        return await original_fetchval(sql, *args)

    case.tx.fetchrow, case.tx.execute, case.tx.fetchval = fetchrow, execute, fetchval
    monkeypatch.setattr(processor, 'enqueue', case.kernel.enqueue)
    if not assigned:
        case.state['operator_id'] = None
        with pytest.raises(PublicError, match='recovery_assignment_unavailable'):
            await processor.process(case.tx, body, 'late-result')
        assert not receipts and not case.state['reconciliations']
        assert attempt['state'] == 'declined'
        return
    value = await processor.process(case.tx, body, 'late-result')
    assert case.state['reconciliations'][0][4] == case.current.responsible_actor_id
    assert case.state['reconciliations'][0][4] != case.order['buyer_id']
    assert value['code'] == 'reconciliation_required' and not value['paid']
    assert attempt['state'] == 'held'
    assert clock.expiry_decision(case.order, [attempt], case.now) == 'hold'
    assert (await case.kernel.financial_readiness(case.tx, case.order['id']))['movement_status'] == 'reconciliation'
    with pytest.raises(PublicError, match='money_reconciliation_required'):
        await reserve(case)
    assert await processor.process(case.tx, body, 'retry') == value
    assert len(case.state['reconciliations']) == 1 and not case.state['postings']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['refund', 'release', 'failed_authentication', 'job_fee'])
async def test_newer_uncertainty_after_decline_preserves_receipt_and_blocks_replacement(ledger, kind):
    case = ledger
    request = case.request
    if kind == 'job_fee':
        money = economics('service_job')
        case.current.money = case.current.money.model_validate(money)
        case.order.update(order_kind='service_job', total_minor=500000)
        case.state['snapshot'] = {key: value for key, value in money.items()
                                  if key not in {'order_kind', 'refundable_max_minor'}}
    if kind in {'failed_authentication', 'job_fee'}:
        request = collection(case, kind)
    elif kind == 'release':
        request = request.model_copy(update={'kind': 'release', 'amount_minor': 515000,
            'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None,
            'destination': request.destination.model_copy(update={'owner_id': case.order['seller_id']})})
    await reserve(case, request)
    declined, declined_raw = await deliver(case, request, outcome='declined', sequence=2)
    declined_receipts = dict(case.state['callbacks'])
    final_row = dict(case.state['operations'][request.operation_id])
    revision = case.order['financial_revision']
    value, raw = await deliver(case, request, outcome='pending', sequence=3)
    assert value == declined | {'pending_reason': 'reconciliation_required'}
    assert case.state['operations'][request.operation_id] == final_row
    assert case.order['financial_revision'] == revision + 1
    assert len(case.state['reconciliations']) == 1
    assert not case.state['postings'] and not case.state['entries']
    producer = 'trust' if case.order['order_kind'] == 'sale' else 'service-operations'
    assert await case.kernel.lookup(case.tx, request, case.reader, producer=producer) == value
    assert await reserve(case, request) == value
    with pytest.raises(PublicError, match='money_reconciliation_required'):
        await reserve(case, request.model_copy(update={'operation_id': uuid4()}))
    from bt_contracts.orders.payments.signatures import sign
    for receipt in (raw, declined_raw):
        assert await case.kernel.settle(case.tx, receipt, sign(receipt)) == value
    assert (await deliver(case, request, outcome='pending', sequence=4))[0] == value
    assert len(case.state['reconciliations']) == 1
    assert case.order['financial_revision'] == revision + 1
    assert all(case.state['callbacks'][event_id] == receipt
               for event_id, receipt in declined_receipts.items())


@pytest.mark.asyncio
@pytest.mark.parametrize('sequence', [1, 2])
async def test_older_or_equal_pending_after_decline_does_not_create_uncertainty(ledger, sequence):
    case = ledger
    await reserve(case)
    declined, _ = await deliver(case, outcome='declined', sequence=2)
    value, _ = await deliver(case, outcome='pending', sequence=sequence)
    assert value == declined
    assert not case.state['reconciliations']


@pytest.mark.asyncio
@pytest.mark.parametrize('shipping,tax', [(2000, 0), (2000, 300)])
async def test_full_watch_refund_then_settle_remaining_accepted_charges(ledger, shipping, tax):
    case = ledger
    money = economics() | {'shipping_minor': shipping, 'tax_minor': tax,
                           'payable_minor': 515000 + shipping + tax}
    case.current.money = case.current.money.model_validate(money)
    case.order['total_minor'] = money['payable_minor']
    case.state['snapshot'] = {key: value for key, value in money.items()
                              if key not in {'order_kind', 'refundable_max_minor'}}
    await reserve(case)
    await deliver(case)
    assert (await case.kernel.financial_readiness(case.tx, case.order['id']))['held_minor'] == shipping + tax
    charge = collection(case)
    await reserve(case, charge)
    await deliver(case, charge)
    case.current.fee_already_collected = True
    release = case.contract.Movement.model_validate(case.request.model_dump() | {
        'operation_id': uuid4(), 'kind': 'release', 'amount_minor': shipping + tax,
        'recipient_id': case.order['seller_id'], 'original_payment_attempt_id': None,
        'destination': case.request.destination.model_dump() | {'owner_id': case.order['seller_id']},
        'release_amounts': dict(gross_minor=shipping + tax, business_fee_minor=0,
            buyer_fee_minor=0, shipping_minor=shipping, tax_minor=tax, transfer_minor=0)})
    case.current.release_ready = False
    case.current.received_at = None
    case.current.window_ends_at = None
    with pytest.raises(PublicError, match='release_prerequisites_required'):
        await reserve(case, release)
    case.current.charges_ready = True
    case.current.hold = True
    with pytest.raises(PublicError, match='release_prerequisites_required'):
        await reserve(case, release)
    case.current.hold = False
    wrong = release.model_copy(update={'amount_minor': shipping + tax + 15000})
    with pytest.raises(PublicError, match='release_amount_mismatch'):
        await reserve(case, wrong)
    pending = await reserve(case, release)
    assert await reserve(case, release) == pending
    confirmed, raw = await deliver(case, release)
    from bt_contracts.orders.payments.signatures import sign
    assert await case.kernel.settle(case.tx, raw, sign(raw)) == confirmed
    postings = [row for row in case.state['entries'] if row[0] == release.operation_id]
    assert {row[1]: row[2] for row in postings} == (
        {'buyer_held': shipping + tax, 'transport_payable': -shipping}
        | ({'tax_payable': -tax} if tax else {}))
    assert sum(row[2] for row in postings) == 0
    assert (await case.kernel.financial_readiness(case.tx, case.order['id']))['held_minor'] == 0
    assert len(case.state['postings']) == 3
