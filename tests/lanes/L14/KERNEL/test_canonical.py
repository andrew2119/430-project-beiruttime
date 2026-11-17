from datetime import datetime, timedelta, timezone
from uuid import UUID
import json

import pytest
from pydantic import ValidationError
from conftest import load, ROOT
from bt_contracts.auction.core.kernel_v4 import KernelCommand, KernelReceipt, decide

canonical = load('canonical_v4', 'services/auction/modules/rules/kernel-v2/canonical.py')
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def lot(**changes):
    return dict(currency='USD', mode='bidding', revision=1, watch_id=UUID(int=2), accepted_sequence=0,
                first_bid_confirmed=False, scheduled_ends_at=NOW, leader_id=None,
                reserve_minor=None, opening_minor=400000, current_minor=400000, **changes)


def command(**changes):
    data = dict(operation_id=UUID(int=1), auction_id=UUID(int=3), watch_id=UUID(int=2),
                actor_id=UUID(int=4), organization_id=None, expected_revision=1,
                policy_revision=1, action='close')
    data.update(changes)
    return KernelCommand(**data)


@pytest.mark.parametrize('offset,expected', [(-1, 'auction_not_ended'), (0, 'no_sale'), (1, 'no_sale')])
def test_exact_fixed_end(offset, expected):
    assert decide(lot(), 'close', NOW + timedelta(microseconds=offset))[2] == expected


@pytest.mark.parametrize('mode', ['prebid_pending', 'prebid_reserved'])
def test_legacy_ends_without_release(mode):
    value = lot()
    value['mode'] = mode
    assert decide(value, 'close', NOW) == ('ended_legacy_review', 'pending', 'legacy_outcome_review')


def test_public_price_alone_meets_reserve():
    value = lot()
    value.update(accepted_sequence=2, leader_id=UUID(int=4), reserve_minor=450000)
    assert decide(value, 'close', NOW)[0] == 'closed_no_sale'
    value['current_minor'] = 450000
    assert decide(value, 'close', NOW)[0] == 'closed_winner'


def test_cancellation_fences_racing_bid_and_can_finish_after_end():
    value = lot()
    assert decide(value, 'cancel', NOW - timedelta(seconds=1))[0] == 'cancellation_pending'
    value['mode'] = 'cancellation_pending'
    assert decide(value, 'close', NOW)[1] == 'pending'
    assert decide(value, 'confirm_cancellation', NOW)[0] == 'cancelled'
    value.update(mode='bidding', accepted_sequence=1)
    assert decide(value, 'cancel', NOW - timedelta(seconds=1))[2] == 'cancellation_denied'
    value.update(accepted_sequence=0, first_bid_confirmed=True)
    assert decide(value, 'cancel', NOW - timedelta(seconds=1))[2] == 'cancellation_denied'


class Transaction:
    def __init__(self):
        self.lot = lot()
        self.retained = None
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if sql.startswith('INSERT'):
            self.retained = dict(command=args[2], receipt=args[3])

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if 'l14_kernel_operations' in sql:
            return self.retained
        if sql.startswith('UPDATE'):
            self.lot.update(mode=args[1], revision=self.lot['revision'] + 1)
        return dict(self.lot)

    async def fetchval(self, sql):
        return NOW


async def allowed(tx, cmd, current):
    assert current['watch_id'] == cmd.watch_id
    return UUID(int=5)


@pytest.mark.asyncio
async def test_lost_response_retry_and_conflicting_binding():
    tx = Transaction()
    first = await canonical.execute(tx, command(), allowed)
    assert first.mode == 'closed_no_sale' and first.revision == 2
    assert await canonical.execute(tx, command(), allowed) == first
    assert await canonical.lookup(tx, command(), allowed) == first
    assert sum(sql.startswith('UPDATE') for sql, _ in tx.calls) == 1
    assert tx.calls[0][1][0].startswith('operation:')
    assert tx.calls[1][1][0].startswith('auction:')
    with pytest.raises(ValueError, match='conflicts'):
        await canonical.execute(tx, command(policy_revision=2), allowed)


@pytest.mark.asyncio
async def test_stale_and_current_permission_denial():
    tx = Transaction()
    result = await canonical.execute(tx, command(expected_revision=2), allowed)
    assert result.code == 'stale_revision' and tx.lot['revision'] == 1

    async def denied(*args):
        raise PermissionError('Current permission is required')

    with pytest.raises(PermissionError):
        await canonical.lookup(tx, command(expected_revision=2), denied)
    empty = Transaction()
    with pytest.raises(ValueError, match='unavailable'):
        await canonical.lookup(empty, command(), allowed)
    assert empty.retained is None


def test_strict_envelopes_and_fixtures():
    with pytest.raises(ValidationError):
        command(expected_revision=True)
    fixtures = json.loads((ROOT / 'packages/contracts-auction/core/fixtures/kernel.v4.json').read_text())
    for value in fixtures['receipts']:
        receipt = KernelReceipt.model_validate(value)
        with pytest.raises(ValidationError):
            KernelReceipt.model_validate({**value, 'maxima': []})
        assert receipt.code in fixtures['messages']
        assert set(fixtures['messages'][receipt.code]) == {'en', 'ar'}


def test_current_state_has_bounded_money_and_no_private_fields():
    from bt_contracts.auction.core.kernel_v4 import current_state
    value = lot()
    value.update(mode='prebid_pending', starts_at=NOW - timedelta(days=1), end_version=1,
                 close_version=0, maxima=[{'amount_minor': 900000}], reserve_minor=800000)
    result = current_state(value, NOW).model_dump(mode='json')
    assert result['status'] == 'ended'
    assert not {'maxima', 'reserve_minor', 'leader_id'} & result.keys()
    for amount in (True, 9_000_000_000_001, -1):
        value['current_minor'] = amount
        with pytest.raises(ValidationError):
            current_state(value, NOW)


@pytest.mark.asyncio
async def test_legacy_resolution_requires_current_proof_and_never_reopens():
    tx = Transaction()
    tx.lot['mode'] = 'ended_legacy_review'

    async def unknown(*args):
        raise PermissionError('Legacy outcome remains unknown')

    cmd = command(action='resolve_legacy_no_sale')
    with pytest.raises(PermissionError):
        await canonical.execute(tx, cmd, unknown)
    assert tx.lot['mode'] == 'ended_legacy_review' and tx.retained is None
    result = await canonical.execute(tx, cmd, allowed)
    assert result.mode == 'closed_no_sale' and result.code == 'no_sale'
    assert decide(tx.lot, 'cancel', NOW)[2] == 'auction_final'


@pytest.mark.asyncio
async def test_current_follow_up_is_bound_to_auction_watch_and_revision():
    from bt_contracts.auction.core.kernel_v4 import current_state
    tx = Transaction()
    tx.lot.update(accepted_sequence=1, leader_id=UUID(int=4), id=UUID(int=3),
                  starts_at=NOW - timedelta(days=1), end_version=1, close_version=1)
    receipt = await canonical.execute(tx, command(), allowed)
    result = current_state(tx.lot, NOW, receipt)
    assert result.pending_reason == 'allocation_pending'
    assert result.next_actor == UUID(int=5)
    assert result.next_review_at == NOW + timedelta(hours=24)
    for update in (dict(auction_id=UUID(int=6)), dict(watch_id=UUID(int=6)), dict(revision=3)):
        wrong = receipt.model_copy(update=update)
        with pytest.raises(ValueError, match='unavailable'):
            current_state(tx.lot, NOW, wrong)
    with pytest.raises(ValueError, match='unavailable'):
        current_state(tx.lot, NOW)


@pytest.mark.asyncio
async def test_pending_requires_responsible_person():
    tx = Transaction()
    tx.lot.update(mode='prebid_pending')

    async def missing(*args):
        return None

    with pytest.raises(ValidationError, match='responsible'):
        await canonical.execute(tx, command(), missing)
    assert tx.retained is None


@pytest.mark.parametrize('currency', ['LBP', None, 'usd'])
@pytest.mark.parametrize('action', ['close', 'cancel', 'confirm_cancellation', 'resolve_legacy_no_sale'])
@pytest.mark.asyncio
async def test_non_usd_remains_unchanged_with_retained_reconciliation(currency, action):
    from bt_contracts.auction.core.kernel_v4 import current_state
    tx = Transaction()
    tx.lot.update(currency=currency, current_minor=500000, accepted_sequence=2,
                  leader_id=UUID(int=4), mode='prebid_reserved')
    original = dict(tx.lot)
    cmd = command(action=action)
    receipt = await canonical.execute(tx, cmd, allowed)
    assert receipt.state == 'pending'
    assert receipt.code == 'currency_reconciliation_required'
    assert receipt.next_actor == UUID(int=5)
    assert receipt.next_review_at == NOW + timedelta(hours=24)
    assert tx.lot == original
    assert not any(sql.startswith('UPDATE') for sql, _ in tx.calls)
    assert await canonical.execute(tx, cmd, allowed) == receipt
    assert await canonical.lookup(tx, cmd, allowed) == receipt
    assert 'current_minor' not in receipt.model_dump()
    with pytest.raises(ValueError, match='currency reconciliation'):
        current_state(tx.lot, NOW, receipt)


@pytest.mark.parametrize('mode', ['bidding', 'closed_winner', 'ended_legacy_review'])
def test_missing_currency_never_selects_winner_or_exposes_active_amount(mode):
    from bt_contracts.auction.core.kernel_v4 import current_state
    value = lot()
    value.update(mode=mode, accepted_sequence=2, leader_id=UUID(int=4), current_minor=500000)
    del value['currency']
    assert decide(value, 'close', NOW) == (mode, 'pending', 'currency_reconciliation_required')
    with pytest.raises(ValueError, match='unavailable'):
        current_state(value, NOW)


@pytest.mark.parametrize('offset,status', [(-2, 'scheduled'), (-1, 'live'), (0, 'ended')])
def test_no_bid_zero_current_state(offset, status):
    from bt_contracts.auction.core.kernel_v4 import current_state
    value = lot()
    value.update(current_minor=0, starts_at=NOW - timedelta(seconds=1),
                 end_version=1, close_version=0)
    result = current_state(value, NOW + timedelta(seconds=offset))
    assert result.current_minor == 0 and result.status == status
    assert decide(value, 'close', NOW) == ('closed_no_sale', 'succeeded', 'no_sale')


@pytest.mark.parametrize('field', ['opening_minor', 'current_minor', 'reserve_minor'])
@pytest.mark.parametrize('amount', [True, -1, 9_000_000_000_001, 400000.0])
@pytest.mark.asyncio
async def test_invalid_retained_cents_never_record_result(field, amount):
    tx = Transaction()
    tx.lot.update(accepted_sequence=1, leader_id=UUID(int=4))
    tx.lot[field] = amount
    original = dict(tx.lot)
    with pytest.raises(ValueError, match='retained economics'):
        await canonical.execute(tx, command(), allowed)
    assert tx.lot == original and tx.retained is None
    assert not any(sql.startswith('UPDATE') for sql, _ in tx.calls)


def test_close_accepts_upper_money_bound():
    value = lot()
    value.update(accepted_sequence=1, leader_id=UUID(int=4),
                 opening_minor=9_000_000_000_000, current_minor=9_000_000_000_000,
                 reserve_minor=9_000_000_000_000)
    assert decide(value, 'close', NOW) == ('closed_winner', 'succeeded', 'allocation_pending')
