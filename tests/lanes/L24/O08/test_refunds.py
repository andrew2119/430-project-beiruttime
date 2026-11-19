import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError
from bt_contracts.orders.refunds.v1 import Authority, Command, Facts, Line, Operation
from refunds.domain import Refused, plan
from refunds.service import Refunds

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def uid(n):
    return UUID(int=n)


def command(**changes):
    return Command(**(dict(operation_id=uid(1), subject_id=uid(2), watch_id=uid(3),
        actor_id=uid(4), organization_id=uid(5), expected_revision=1, source_revision=1,
        quote_id=uid(6), quote_revision=1, policy_revision=1, basis_id=uid(7),
        amount_minor=500000) | changes))


def facts(**changes):
    return Facts(**(dict(subject_id=uid(2), watch_id=uid(3), organization_id=uid(5),
        buyer_id=uid(8), quote_id=uid(6), quote_revision=1, policy_revision=1,
        revision=1, source_revision=1, basis_id=uid(7), kind='watch',
        basis='failed_authentication', basis_approved=True, payment_state='paid_held', basis_valid_until=NOW+timedelta(days=1),
        paid_principal_minor=500000, retained_principal_minor=500000, approved_minor=500000,
        confirmed_minor=0, unresolved_minor=0, business_fee_minor=25000,
        custody_transferred=True, controlled_return_received=False, recorded_failure_exception=False,
        private_sale=True, failed_inspection=True, lines=()) | changes))


def authority(**changes):
    return Authority(**(dict(actor_id=uid(4), organization_id=uid(5), subject_id=uid(2),
        watch_id=uid(3), can_refund=True, current_assignment=True) | changes))


def test_failed_authentication_without_buyer_receipt_or_pass():
    result = plan(command(), facts(), authority(), NOW)
    assert result.command.amount_minor == 500000
    assert result.buyer_id == uid(8)
    assert result.next_review_at == NOW + timedelta(hours=24)


@pytest.mark.parametrize('changes,code', [
    ({'amount_minor':500001}, 'cap_exceeded'),
    ({'expected_revision':2}, 'stale'), ({'source_revision':2}, 'stale'),
    ({'quote_revision':2}, 'stale'), ({'policy_revision':2}, 'stale'),
    ({'basis_id':uid(19)}, 'stale'), ({'organization_id':uid(19)}, 'denied'),
    ({'actor_id':uid(19)}, 'denied'), ({'watch_id':uid(19)}, 'denied')])
def test_request_rejections(changes, code):
    with pytest.raises(Refused, match=code):
        plan(command(**changes), facts(), authority(), NOW)


@pytest.mark.parametrize('changes', [{'can_refund':False}, {'current_assignment':False}])
def test_revoked_authority(changes):
    with pytest.raises(Refused, match='denied'):
        plan(command(), facts(), authority(**changes), NOW)


@pytest.mark.parametrize('offset,allowed', [(-1,True),(0,False),(1,False)])
def test_expiry_boundary(offset, allowed):
    source = facts(basis_valid_until=NOW)
    instant = NOW + timedelta(microseconds=offset)
    if allowed:
        assert plan(command(), source, authority(), instant)
    else:
        with pytest.raises(Refused, match='basis_required'):
            plan(command(), source, authority(), instant)


@pytest.mark.parametrize('changes,code', [
    ({'payment_state':'released'}, 'basis_required'),
    ({'payment_state':'pending'}, 'basis_required'),
    ({'payment_state':'unpaid'}, 'basis_required'),
    ({'failed_inspection':False}, 'basis_required'),
    ({'private_sale':False}, 'basis_required'),
    ({'basis_approved':False}, 'basis_required'),
    ({'basis':'cancellation'}, 'return_required'),
    ({'paid_principal_minor':0}, 'cap_exceeded'),
    ({'confirmed_minor':1}, 'cap_exceeded'),
    ({'unresolved_minor':1}, 'cap_exceeded')])
def test_source_rejections(changes, code):
    with pytest.raises(Refused, match=code):
        plan(command(), facts(**changes), authority(), NOW)


def test_full_job_gross_and_fee_reference_are_separate():
    source = facts(kind='job', basis='cancellation', custody_transferred=False)
    result = plan(command(), source, authority(), NOW)
    assert result.command.amount_minor == 500000
    assert result.business_fee_receivable_minor == 25000
    another = plan(command(amount_minor=1), source, authority(), NOW)
    assert result.fee_collection_key == another.fee_collection_key


def test_retained_partial_job_lines():
    rows = [Line(line_id=uid(20+i), amount_minor=10000, kind=kind, accepted=accepted,
                 performed_or_consumed=used, unused_returnable=returnable)
            for i, (kind,accepted,used,returnable) in enumerate([
                ('labor',True,False,False), ('part',True,False,True),
                ('part',True,True,True), ('labor',False,False,False),
                ('assessment',True,False,False), ('transport',True,False,True),
                ('part',True,False,False)])]
    source = facts(kind='job', basis='partial_work', custody_transferred=False, lines=rows)
    assert plan(command(amount_minor=20000), source, authority(), NOW).cap_minor == 20000
    with pytest.raises(Refused, match='cap_exceeded'):
        plan(command(amount_minor=20001), source, authority(), NOW)


@pytest.mark.parametrize('amount', [True, 1.5, '100', float('inf'), -1, 0, 9000000000000001])
def test_finite_integer_money(amount):
    with pytest.raises(ValidationError):
        command(amount_minor=amount)


class JournalFixture:
    """Synthetic journal contract fixture; never a connected payment proof."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, body TEXT, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY)')
        self.lock = asyncio.Lock()
        self.current = authority()
        self.source = facts()
        self.lose_response = False

    @asynccontextmanager
    async def refund_transaction(self, cmd):
        async with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            if self.lose_response:
                self.lose_response = False
                raise ConnectionError()

    async def authority(self, cmd):
        return self.current

    async def prior(self, cmd):
        row = self.db.execute('SELECT body,result FROM receipts WHERE id=?', (str(cmd.operation_id),)).fetchone()
        if row:
            if row[0] != cmd.model_dump_json():
                raise Refused('conflict')
            return Operation.model_validate_json(row[1])

    async def facts(self, cmd):
        rows = self.db.execute('SELECT result FROM receipts').fetchall()
        unresolved = sum(Operation.model_validate_json(row[0]).amount_minor for row in rows)
        return self.source.model_copy(update={'unresolved_minor':unresolved, 'revision':1+len(rows)})

    async def reserve(self, value):
        cmd = value.command
        result = Operation(**{key:getattr(cmd,key) for key in (
            'operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision','amount_minor')},
            state='pending',revision=cmd.expected_revision+1,pending_reason='processing',
            next_actor='payout_operator',next_review_at=value.next_review_at)
        self.db.execute('INSERT INTO receipts VALUES (?,?,?)',
                        (str(cmd.operation_id),cmd.model_dump_json(),result.model_dump_json()))
        self.db.execute('INSERT INTO outbox VALUES (?)', (str(cmd.operation_id),))
        return result

    async def lookup(self, operation_id, actor_id, organization_id):
        if not self.current.can_refund or not self.current.current_assignment or (
            actor_id, organization_id) != (self.current.actor_id,self.current.organization_id):
            raise Refused('denied')
        row = self.db.execute('SELECT result FROM receipts WHERE id=?', (str(operation_id),)).fetchone()
        if row:
            result = Operation.model_validate_json(row[0])
            if (result.subject_id,result.watch_id) != (self.current.subject_id,self.current.watch_id):
                raise Refused('denied')
            return result


@pytest.mark.asyncio
async def test_lost_response_restart_duplicate_and_revocation(tmp_path):
    path = tmp_path / 'refunds.db'
    journal = JournalFixture(path)
    journal.lose_response = True
    with pytest.raises(Refused, match='pending'):
        await Refunds(journal, lambda:NOW).request(command())
    journal.db.close()
    restarted = JournalFixture(path)
    service = Refunds(restarted, lambda:NOW)
    result = await service.request(command())
    assert result.state == 'pending'
    assert await service.lookup(uid(1),uid(4),uid(5)) == result
    assert restarted.db.execute('SELECT count(*) FROM outbox').fetchone()[0] == 1
    with pytest.raises(Refused, match='conflict'):
        await service.request(command(amount_minor=1))
    restarted.current = authority(can_refund=False)
    with pytest.raises(Refused, match='denied'):
        await service.request(command())
    with pytest.raises(Refused, match='denied'):
        await service.lookup(uid(1),uid(4),uid(5))
    restarted.db.close()


@pytest.mark.asyncio
async def test_racing_partial_refunds_keep_unknown_reserved(tmp_path):
    journal = JournalFixture(tmp_path / 'race.db')
    service = Refunds(journal, lambda:NOW)
    results = await asyncio.gather(service.request(command(amount_minor=300000)),
        service.request(command(operation_id=uid(90),amount_minor=300000)),return_exceptions=True)
    assert sum(isinstance(result,Operation) for result in results) == 1
    assert any(isinstance(result,Refused) and result.code == 'stale' for result in results)
    with pytest.raises(Refused,match='cap_exceeded'):
        await service.request(command(operation_id=uid(90),amount_minor=300000,expected_revision=2))
    assert (await service.request(command(operation_id=uid(90),amount_minor=200000,expected_revision=2))).state == 'pending'
    journal.db.close()


def test_contract_fixtures():
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    examples = json.loads((root / 'packages/contracts-orders/refunds/fixtures.json').read_text())
    for example in examples:
        request = Command.model_validate(example['command'])
        source = Facts.model_validate(example['facts'])
        current = Authority.model_validate(example['authority'])
        if example['code'] == 'permitted':
            assert plan(request,source,current,NOW)
        else:
            with pytest.raises(Refused,match=example['code']):
                plan(request,source,current,NOW)


@pytest.mark.asyncio
async def test_actual_timeout_never_creates_a_replacement_reference(tmp_path):
    journal = JournalFixture(tmp_path / 'timeout.db')
    original = journal.facts

    async def slow(cmd):
        await asyncio.sleep(3)
        return await original(cmd)

    journal.facts = slow
    service = Refunds(journal, lambda:NOW)
    with pytest.raises(Refused,match='pending'):
        await service.request(command())
    assert journal.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0
    journal.facts = original
    assert (await service.request(command())).operation_id == uid(1)
    journal.db.close()


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_reservation_and_receipt(tmp_path):
    journal = JournalFixture(tmp_path / 'rollback.db')
    journal.db.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    service = Refunds(journal, lambda:NOW)
    with pytest.raises(sqlite3.IntegrityError):
        await service.request(command())
    assert journal.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0
    journal.db.execute('DROP TRIGGER fail_outbox')
    assert (await service.request(command())).state == 'pending'
    journal.db.close()


def test_duplicate_and_excessive_retained_lines_rejected():
    row=Line(line_id=uid(20),amount_minor=1,kind='part',accepted=True,
             performed_or_consumed=False,unused_returnable=True)
    with pytest.raises(ValidationError):
        facts(lines=(row,row))
    with pytest.raises(ValidationError):
        facts(lines=(row,)*201)


def test_operation_recovery_schema():
    with pytest.raises(ValidationError):
        Operation(**{key:getattr(command(),key) for key in (
            'operation_id','subject_id','watch_id','actor_id','organization_id','expected_revision','amount_minor')},
            state='pending',revision=2,pending_reason=None,next_actor=None,next_review_at=None)
