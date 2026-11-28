"""Contract-identical local source cases; connected acceptance is separate."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bt_runtime.principal import CurrentPrincipal
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def fixture():
    return json.loads((ROOT / 'packages/contracts-orders/cancellations/fixtures.json').read_text())


def test_fixtures(modules):
    v1, policy, _ = modules
    data = fixture()
    for case in data['cases']:
        command = v1.Command(**(data['command'] | case.get('command', {})))
        facts = v1.Facts(**(data['facts'] | case.get('facts', {})))
        result = policy.decide(command, facts, facts.buyer_id, NOW)
        for key, value in case['expected'].items():
            assert result.model_dump(mode='json')[key] == value, case['name']
        assert result.effect != 'release_commitment' or result.refundable_minor == 0


@pytest.mark.parametrize('hours', [24, 48])
@pytest.mark.parametrize('offset', [-1, 0, 1])
def test_retained_review_boundaries_after_restart(modules, hours, offset):
    v1, policy, _ = modules
    data = fixture()
    command = v1.Command(**data['command'])
    facts = v1.Facts(**(data['facts'] | {'payment': 'unknown'}))
    initial = policy.decide(command, facts, facts.buyer_id, NOW)
    # Canonical apply retains these fields atomically with the hold and revision.
    retained = facts.model_dump(mode='json') | {
        'cancellation_state': 'pending', 'revision': initial.revision,
        'hold_started_at': initial.hold_started_at.isoformat(),
        'last_progress_at': None,
    }
    restored = v1.Facts.model_validate_json(json.dumps(retained))
    later = NOW + timedelta(hours=hours, seconds=offset)
    following = command.model_copy(update={'expected_revision': restored.revision})
    result = policy.decide(following, restored, facts.buyer_id, later)
    assert result.next_review_at == NOW + timedelta(hours=24)
    assert result.escalation_at == NOW + timedelta(hours=48)
    assert result.review_overdue == (later >= NOW + timedelta(hours=24))
    assert result.escalated == (later >= NOW + timedelta(hours=48))
    assert result.next_actor == (facts.escalation_actor if result.escalated else facts.responsible_actor)
    assert result.hold_started_at == NOW
    assert result.effect == 'pause_fulfilment'
    assert not result.completed


def test_progress_and_overdue_hold(modules):
    v1, policy, _ = modules
    data = fixture()
    facts = v1.Facts(**(data['facts'] | {
        'payment': 'unknown', 'cancellation_state': 'pending', 'hold_started_at': NOW,
    }))
    command = v1.Command(**data['command'])
    overdue = policy.decide(command, facts, facts.buyer_id, NOW + timedelta(hours=49))
    assert overdue.next_review_at == NOW + timedelta(hours=24)
    assert overdue.escalated
    progress = NOW + timedelta(hours=30)
    facts = v1.Facts.model_validate(facts.model_dump() | {'last_progress_at': progress})
    updated = policy.decide(command, facts, facts.buyer_id, NOW + timedelta(hours=49))
    assert updated.hold_started_at == NOW
    assert updated.last_progress_at == progress
    assert updated.next_review_at == progress + timedelta(hours=24)
    assert updated.escalation_at == progress + timedelta(hours=48)
    assert not updated.escalated


def test_missing_or_invalid_retained_timing_fails_closed(modules):
    v1, _, _ = modules
    data = fixture()['facts']
    for changes in (
        {'cancellation_state': 'pending'},
        {'hold_started_at': NOW, 'last_progress_at': NOW - timedelta(seconds=1)},
        {'hold_started_at': '2026-11-17T00:00:00'},
    ):
        with pytest.raises(ValidationError):
            v1.Facts(**(data | changes))


@pytest.mark.parametrize('field,value', [('principal_minor', 1.5), ('principal_minor', True),
                                         ('principal_minor', -1), ('principal_minor', 9007199254740992)])
def test_integer_money(modules, field, value):
    with pytest.raises(ValidationError):
        modules[0].Facts(**(fixture()['facts'] | {field: value}))


@pytest.mark.parametrize('recovery_index', [0, 1])
def test_duplicate_restart_lost_response_and_scope(modules, recovery_index):
    v1, _, service = modules
    data = fixture()
    recovery = data['recovery_cases'][recovery_index]
    command = v1.Command(**recovery['command'])
    facts = v1.Facts(**data['facts'])
    actor = CurrentPrincipal(actor={'subject_id': facts.buyer_id, 'organization_id': None, 'session_id': 'synthetic-session'})
    durable = {}
    effects = []

    class Provider:
        allowed = True
        lost = recovery.get('first_delivery') == 'response_lost_after_commit'
        @asynccontextmanager
        async def transaction(self, command, principal):
            self.facts = v1.Facts.model_validate(durable.get('facts', facts.model_dump())).model_dump()
            yield self
            if self.lost:
                self.lost = False
                raise TimeoutError()

        async def authorized(self, action):
            return self.allowed

        async def receipt(self, operation):
            return durable.get(str(operation))

        async def apply(self, result):
            effects.append(result.effect)

        async def save(self, command, principal, result):
            durable['facts'] = facts.model_dump(mode='json') | {
                'cancellation_state': result.state, 'revision': result.revision,
                'hold_started_at': result.hold_started_at, 'last_progress_at': result.last_progress_at,
            }
            durable[str(command.operation_id)] = {'command': command.model_dump(mode='json'),
                'actor_id': str(principal.actor.subject_id), 'result': result}

        async def lookup(self, subject, operation, principal):
            if not self.allowed or principal.actor.subject_id != facts.buyer_id or subject != facts.subject_id:
                raise service.Denied()
            return durable.get(str(operation), {}).get('result')

    async def run():
        if Provider.lost:
            with pytest.raises(service.Unavailable):
                await service.execute(Provider(), command, actor, NOW)
        else:
            await service.execute(Provider(), command, actor, NOW)
        fresh = Provider()
        fresh.lost = False
        result = await service.execute(fresh, command, actor, NOW)
        assert result.completed
        assert result.state == recovery['expected_state']
        assert str(command.operation_id) == recovery['retry_operation_id']
        assert effects == ['release_commitment'] * recovery['expected_effect_count']
        assert await service.lookup(fresh, facts.subject_id, command.operation_id, actor) == result
        with pytest.raises(service.Conflict):
            await service.execute(fresh, command.model_copy(update={'reason': 'changed'}), actor, NOW)
        fresh.allowed = False
        with pytest.raises(service.Denied):
            await service.execute(fresh, command, actor, NOW)
        with pytest.raises(service.Denied):
            await service.lookup(fresh, facts.subject_id, command.operation_id, actor)
        with pytest.raises(service.Unavailable):
            await service.execute(None, command, actor, NOW)
    asyncio.run(run())


def test_languages_and_memory_contract():
    root = ROOT / 'web/features/cancellations'
    en, ar = (json.loads((root / f'{language}.json').read_text()) for language in ('en', 'ar'))
    assert en.keys() == ar.keys()
    assert all(en.values()) and all(ar.values())
    source = (root / 'page.tsx').read_text()
    assert 'key={session.access_fingerprint}' in source
    assert 'key={locale}' not in source
    assert 'localStorage' not in source and 'sessionStorage' not in source
    assert 'operation??' in source and "cache:'no-store'" in source


def test_current_decision_visible_without_mutating_receipt(modules, monkeypatch):
    from cancellations.provider import TransactionalProvider
    from cancellations import repository
    v1, policy, service = modules
    data = fixture()
    facts = v1.Facts(**(data['facts'] | {'payment': 'paid_held', 'cancellation_state': 'pending', 'hold_started_at': NOW}))
    command = v1.Command(**data['command'])
    original = policy.decide(command, facts, facts.buyer_id, NOW)
    actor = CurrentPrincipal(actor={'subject_id': facts.buyer_id, 'session_id': 'synthetic-session'})
    reads = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield self

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    class Source:
        allowed = True
        async def lock(self, tx, subject, watch, principal):
            assert subject == facts.subject_id
            return facts.model_copy(update={'revision': 6, 'cancellation_state': 'accepted'}).model_dump()

        async def authorized(self, tx, current, principal, action):
            return self.allowed

        async def current(self, tx, current, receipt, principal):
            return receipt.model_copy(update={'state': current.cancellation_state, 'revision': current.revision,
                                              'pending_reason': 'refund_review'})

    async def retained(tx, operation):
        reads.append(operation)
        return dict(actor_id=str(actor.actor.subject_id), command=command.model_dump(mode='json'), result=original)

    monkeypatch.setattr(repository, 'receipt', retained)

    async def run():
        source = Source()
        provider = TransactionalProvider(Pool(), source)
        current = await service.lookup(provider, facts.subject_id, command.operation_id, actor)
        assert current.state == 'accepted'
        assert current.revision == 6
        assert current.operation_id == original.operation_id
        assert original.state == 'pending'
        source.allowed = False
        with pytest.raises(service.Denied):
            await service.lookup(provider, facts.subject_id, command.operation_id, actor)
        assert len(reads) == 1
    asyncio.run(run())


def test_selected_organization_checked_before_receipt(modules):
    v1, _, service = modules
    command = v1.Command(**fixture()['command'])
    actor = CurrentPrincipal(actor={'subject_id': fixture()['facts']['buyer_id'],
        'organization_id': fixture()['facts']['quote_id'], 'session_id': 'synthetic-session'})

    class Provider:
        @asynccontextmanager
        async def transaction(self, command, principal):
            yield self

        async def authorized(self, action):
            raise AssertionError('wrong selected scope must fail first')

    async def run():
        with pytest.raises(service.Denied):
            await service.execute(Provider(), command, actor, NOW)
    asyncio.run(run())


def test_denied_recovery_wiring():
    source = (ROOT / 'web/features/cancellations/page.tsx').read_text()
    assert 'setOutcome(recovery.outcome);setError(recovery.error)' in source
    assert "outcome?.state==='denied'||rejected" in source
    assert 'setPrevious(operation!.operation_id);setOperation(null)' in source
    assert 'setRejected(false)' in source
    assert 'busy||!!outcome||lookupOnly||rejected' in source
