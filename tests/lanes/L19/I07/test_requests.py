import json
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/identity/modules/data-requests'
sys.path.insert(0, str(MODULE))
Store = importlib.import_module("store").Store
policy = importlib.import_module("policy")
DOMAINS, cleanup_due, removable = policy.DOMAINS, policy.cleanup_due, policy.removable
Retention = importlib.import_module("retention").Retention
Adapter = importlib.import_module("adapter").Adapter

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
ARGS = ('person-1', 'person-1', None)


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / 'requests.db', lambda actor, subject, organization: organization in (None, 'org-1'), lambda *args: 'operator-1')
    yield value
    value.close()


def start(store, kind='delete', operation='request-1'):
    return store.create(operation, *ARGS, kind, 0, NOW)


def receipt(domain, revision, state='deleted', **changes):
    return dict(receipt_id=f'{domain}-{revision}', domain=domain, operation_id='request-1', expected_revision=1,
                source_revision=revision, facts_revision=revision, policy_revision='D31.v1', state=state,
                reasons=[], next_review_at=None, obligations_closed_at=None, **changes)


def ack(store, domain, revision, state='deleted', **changes):
    value = receipt(domain, revision, state)
    value.update(changes)
    return store.acknowledge('request-1', *ARGS, domain, value, NOW)


def test_nine_domains_required_and_restart(store):
    start(store)
    for i, domain in enumerate(DOMAINS):
        result = ack(store, domain, i + 1)
        assert result['state'] == ('complete' if i == 8 else 'partial')
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    second = Store(path, store.authority, store.responsible_operator)
    assert second.lookup('request-1', *ARGS, NOW)['state'] == 'complete'
    second.close()


def test_domain_failure_never_complete(store):
    start(store)
    for i, domain in enumerate(DOMAINS):
        result = ack(store, domain, i + 1, 'failed' if i == 8 else 'deleted')
    assert result['state'] == 'partial'
    assert ack(store, DOMAINS[-1], 10)['state'] == 'complete'


@pytest.mark.parametrize('reason', ['active_sale','custody','payout','dispute','financial','audit','active_case'])
def test_reasoned_holds_preserve_obligations(store, reason):
    start(store)
    result = ack(store, 'orders', 1, 'retained', reasons=[reason], next_review_at='2026-11-18T00:00:00Z')
    assert result['state'] == 'held'
    with pytest.raises(ValueError, match='invalid'):
        ack(store, 'orders', 2)
    result = ack(store, 'orders', 2, obligations_closed_at='2026-11-17T00:00:00Z')
    assert result['due_at'] == '2026-12-17T00:00:00Z'


def test_closed_obligation_moves_due_date(store):
    start(store)
    ack(store, 'orders', 1, 'retained', reasons=['custody'], next_review_at='2026-11-18T00:00:00Z')
    value = receipt('orders', 2)
    value['obligations_closed_at'] = '2026-12-01T00:00:00Z'
    result = store.acknowledge('request-1', *ARGS, 'orders', value, NOW + timedelta(days=14))
    assert result['due_at'] == '2026-12-31T00:00:00Z'


def test_duplicate_stale_conflict_and_denial(store):
    assert start(store) == start(store)
    before = receipt('identity', 1)
    first = store.acknowledge('request-1', *ARGS, 'identity', before, NOW)
    assert store.acknowledge('request-1', *ARGS, 'identity', before, NOW) == first
    with pytest.raises(ValueError, match='stale'):
        store.acknowledge('request-1', *ARGS, 'orders', {**receipt('orders', 1), 'expected_revision':99}, NOW)
    before['state'] = 'failed'
    with pytest.raises(ValueError, match='conflict'):
        store.acknowledge('request-1', *ARGS, 'identity', before, NOW)
    with pytest.raises(ValueError, match='conflict'):
        start(store, 'export')
    with pytest.raises(ValueError, match='denied'):
        store.lookup('request-1', 'person-2', 'person-1', None, NOW)
    with pytest.raises(ValueError, match='denied'):
        store.lookup('request-1', *ARGS[:2], 'org-1', NOW)
    with pytest.raises(ValueError, match='denied'):
        store.create('other', *ARGS[:2], 'org-2', 'delete', 0, NOW)
    store.authority = lambda *args: False
    with pytest.raises(ValueError, match='denied'):
        store.lookup('request-1', *ARGS, NOW)


def test_receipt_producer_policy_and_current_facts(store):
    start(store)
    value = receipt('identity', 1)
    with pytest.raises(ValueError, match='denied'):
        store.acknowledge('request-1', *ARGS, 'orders', value, NOW)
    ack(store, 'identity', 1, 'failed')
    value = receipt('identity', 2)
    value['source_revision'] = 1
    with pytest.raises(ValueError, match='stale'):
        store.acknowledge('request-1', *ARGS, 'identity', value, NOW)


def test_timeout_outbox_is_bounded_stable_and_durable(store):
    start(store)
    first = store.dispatch('request-1', *ARGS)
    assert len(first) == 9
    for _ in range(4):
        assert store.dispatch('request-1', *ARGS) == first
    assert store.dispatch('request-1', *ARGS) == []
    assert store.lookup('request-1', *ARGS, NOW)['state'] == 'pending'
    assert start(store)['operation_id'] == 'request-1'


@pytest.mark.parametrize('delta,allowed', [(-1,True),(0,False),(1,False)])
def test_private_export_expiry_and_file_failure(store, delta, allowed):
    start(store, 'export')
    for i, domain in enumerate(DOMAINS):
        result = ack(store, domain, i+1, 'exported')
    assert result['state'] == 'partial'
    ready = store.assemble('request-1', *ARGS, 10, [{'ref':'private-file','size':100}], NOW)
    assert '_files' not in ready and ready['state'] == 'complete'
    time = NOW + timedelta(hours=24, seconds=delta)
    if allowed:
        assert store.download_refs('request-1', *ARGS, time) == [{'ref':'private-file','size':100}]
    else:
        with pytest.raises(ValueError, match='denied'):
            store.download_refs('request-1', *ARGS, time)
        assert store.expired_files('request-1', *ARGS, time)
        assert store.remove_file_ack('request-1', *ARGS, 'private-file', False, time)['state'] == 'partial'
        assert store.remove_file_ack('request-1', *ARGS, 'private-file', True, time)['state'] == 'complete'
    assert '_files' not in store.lookup('request-1', *ARGS, time)


@pytest.mark.parametrize('kind,days', [('unsubmitted',7),('proof',30)])
@pytest.mark.parametrize('delta,expected', [(-1,False),(0,True),(1,True)])
def test_cleanup_boundaries(kind, days, delta, expected):
    due = cleanup_due(kind, NOW, NOW)
    assert due == NOW + timedelta(days=days)
    assert removable(due + timedelta(seconds=delta), due) is expected


def test_audit_anniversary_and_active_case():
    leap = datetime(2024,2,29,tzinfo=timezone.utc)
    assert cleanup_due('audit',leap) == datetime(2025,2,28,tzinfo=timezone.utc)
    assert cleanup_due('proof',NOW,NOW,True) is None
    assert cleanup_due('proof',NOW) is None
    with pytest.raises(ValueError):
        cleanup_due('unsubmitted',NOW.replace(tzinfo=None))


def test_retention_failure_restart_and_active_case(store):
    facts = {'revision':1,'obligations':[],'active_case':True,'final_review_at':'2026-10-01T00:00:00Z'}
    retention = Retention(store, lambda *args: facts)
    retention.register('proof-1', *ARGS, 'proof', NOW-timedelta(days=60))
    assert retention.candidates(*ARGS, NOW) == []
    facts['active_case'] = False
    assert retention.candidates(*ARGS, NOW) == [{'ref':'proof-1','expected_source_revision':1}]
    assert retention.acknowledge('proof-1', *ARGS, 1, False, NOW) == 'partial'
    facts['revision'] = 2
    with pytest.raises(ValueError, match='stale'):
        retention.acknowledge('proof-1', *ARGS, 1, True, NOW)
    assert retention.acknowledge('proof-1', *ARGS, 2, True, NOW) == 'removed'
    assert retention.acknowledge('proof-1', *ARGS, 2, True, NOW) == 'removed'
    assert retention.candidates(*ARGS, NOW) == []


def test_export_size_and_limits(store):
    start(store,'export')
    with pytest.raises(ValueError, match='limit'):
        store.assemble('request-1', *ARGS, 1, [{'ref':'x','size':26*1024*1024}], NOW)
    with pytest.raises(ValueError, match='invalid'):
        store.page(*ARGS, NOW, page_size=51)
    with pytest.raises(ValueError, match='invalid'):
        start(store, kind='other')


def test_contract_fixture_and_adapter(store):
    fixtures = ROOT / 'packages/contracts-identity/data-requests/fixtures'
    scope = SimpleNamespace(actor_id=ARGS[0], subject_id=ARGS[1], organization_id=None)
    adapter = Adapter(store, lambda: NOW)
    result = adapter.command(scope, dict(schema_version='data-requests.v1',operation_id='request-1',kind='delete',expected_revision=0))
    assert result == json.loads((fixtures / 'lost-response.v1.json').read_text())
    assert adapter.lookup(scope,'request-1') == result
    assert adapter.page(scope)['total'] == 1
    with pytest.raises(ValueError,match='invalid'):
        adapter.command(scope, dict(schema_version='data-requests.v1',operation_id='request-2',kind='delete',expected_revision=0,subject_id='person-2'))


def test_parallel_domain_bindings_and_success_fixture(store):
    start(store)
    commands = store.dispatch('request-1', *ARGS)
    for index, command in enumerate(commands):
        assert command['expected_revision'] == 1
        result = ack(store, command['domain'], index+1)
        if index == 0:
            for retry in store.dispatch('request-1', *ARGS):
                assert retry == next(item for item in commands if item['domain'] == retry['domain'])
    fixture = ROOT / 'packages/contracts-identity/data-requests/fixtures/success.v1.json'
    assert result == json.loads(fixture.read_text())


def test_failed_receipts_do_not_reset_retry_bound(store):
    start(store)
    for revision in range(1,6):
        store.dispatch('request-1', *ARGS)
        ack(store, 'orders', revision, 'failed')
    assert not store.dispatch('request-1', *ARGS)


def test_retention_keyset_reaches_later_due_record(store):
    def facts(ref, *args):
        return dict(revision=1, obligations=['custody'] if ref < 'proof-100' else [], active_case=False, final_review_at='2026-10-01T00:00:00Z')
    retention = Retention(store, facts)
    for i in range(101):
        retention.register(f'proof-{i:03}', *ARGS, 'proof', NOW-timedelta(days=60))
    first = retention.scan(*ARGS,NOW)
    assert first == dict(items=[],next_cursor='proof-099')
    second = retention.scan(*ARGS,NOW,after=first['next_cursor'])
    assert second['items'] == [dict(ref='proof-100',expected_source_revision=1)]
    assert retention.acknowledge('proof-100', *ARGS, 1, True, NOW) == 'removed'


@pytest.mark.parametrize('reason', ['active_sale','custody','payout','dispute','financial','active_case'])
def test_audit_references_preserved_during_active_obligations(store, reason):
    facts = dict(revision=1,obligations=[reason],active_case=False,final_review_at=None)
    retention = Retention(store,lambda *args:facts)
    retention.register('audit-1', *ARGS, 'audit', NOW-timedelta(days=800))
    assert retention.scan(*ARGS,NOW)['items'] == []
    with pytest.raises(ValueError,match='stale'):
        retention.acknowledge('audit-1', *ARGS, 1, True, NOW)


def test_export_public_projection_and_fractional_expiry(store):
    start(store,'export')
    for i,domain in enumerate(DOMAINS):
        ack(store,domain,i+1,'exported')
    store.assemble('request-1', *ARGS, 10, [dict(ref='private-file',size=1)], NOW)
    assert '_files' not in start(store,'export')
    boundary = NOW+timedelta(hours=24,microseconds=1)
    assert not store.lookup('request-1', *ARGS, boundary)['export_available']
    assert store.lookup('request-1', *ARGS, boundary)['state'] == 'partial'
    first = store.remove_file_ack('request-1', *ARGS, 'private-file', True, boundary)
    assert store.remove_file_ack('request-1', *ARGS, 'private-file', True, boundary) == first


def test_server_totals_and_all_pages(store):
    body=start(store)
    scope=store._scope(*ARGS)
    assert store.page(*ARGS,NOW)['total'] == 1
    for i in range(1,1000):
        item={**body,'operation_id':f'row-{i:04}'}
        store.db.execute('INSERT INTO requests VALUES(?,?,?)',(item['operation_id'],scope,json.dumps(item)))
    seen=[]
    for page in range(50):
        result=store.page(*ARGS,NOW,page=page)
        assert result['total']==1000
        seen.extend(item['operation_id'] for item in result['items'])
    assert len(set(seen))==1000


def test_lost_response_restart_keeps_dispatch_and_command_identity(store):
    original=start(store)
    sent=store.dispatch('request-1', *ARGS)
    path=store.db.execute('PRAGMA database_list').fetchone()[2]
    restarted=Store(path,store.authority,store.responsible_operator)
    try:
        assert restarted.create('request-1', *ARGS, 'delete', 0, NOW)==original
        assert restarted.dispatch('request-1', *ARGS)==sent
        assert restarted.lookup('request-1', *ARGS,NOW)['state']=='pending'
    finally:
        restarted.close()


def test_receipt_failure_rolls_back_inbox_and_outbox(store):
    start(store)
    save=store._save
    def interrupted(body):
        raise RuntimeError('interrupted')
    store._save=interrupted
    with pytest.raises(RuntimeError):
        ack(store,'orders',1)
    store._save=save
    assert store.db.execute('SELECT count(*) FROM inbox').fetchone()[0]==0
    assert store.db.execute('SELECT count(*) FROM outbox').fetchone()[0]==9
    assert ack(store,'orders',1)['revision']==2


def test_minimal_audit_before_equal_after_anniversary():
    due=cleanup_due('audit',NOW)
    assert not removable(due-timedelta(microseconds=1),due)
    assert removable(due,due)
    assert removable(due+timedelta(microseconds=1),due)


def test_hold_requires_reason_and_review_with_support_bound(store):
    start(store)
    with pytest.raises(ValueError,match='invalid'):
        ack(store,'orders',1,'retained',next_review_at='2026-11-18T00:00:00Z')
    result=ack(store,'orders',1,'retained',reasons=['custody'],next_review_at='2028-11-18T00:00:00Z')
    assert result['next_review_at']=='2026-11-18T00:00:00Z'
    assert result['responsible_operator_id']=='operator-1'
    assert result['next_action']=='review_hold'
    assert result['escalation_at']=='2026-11-19T00:00:00Z'


def test_exhausted_dispatch_requires_current_operator_and_revision(store):
    start(store)
    original = store.dispatch('request-1', *ARGS)
    for _ in range(4):
        store.dispatch('request-1', *ARGS)
    held = store.lookup('request-1', *ARGS, NOW)
    assert held['next_actor'] == 'operator'
    assert held['next_action'] == 'retry_domain'
    assert store.dispatch('request-1', *ARGS) == []
    revision = store.lookup('request-1', *ARGS, NOW)['revision']
    with pytest.raises(ValueError, match='denied'):
        store.recover_dispatch('request-1', *ARGS, 'operator-1', revision)
    store.operator_authority = lambda operator, subject, organization: operator == 'operator-1'
    with pytest.raises(ValueError, match='stale'):
        store.recover_dispatch('request-1', *ARGS, 'operator-1', revision-1)
    recovered = store.recover_dispatch('request-1', *ARGS, 'operator-1', revision)
    assert recovered['next_actor'] == 'domain'
    assert store.dispatch('request-1', *ARGS) == original


@pytest.mark.parametrize('reason', sorted(policy.REASONS))
@pytest.mark.parametrize('terminal', ['deleted', 'redacted'])
def test_failed_receipts_preserve_hold_until_explicit_closure(store, reason, terminal):
    start(store)
    ack(store, 'orders', 1, 'retained', reasons=[reason], next_review_at='2026-11-18T00:00:00Z')
    for revision in (2, 3):
        result = ack(store, 'orders', revision, 'failed')
        assert result['state'] == 'partial'
        assert result['domains']['orders'] == dict(state='failed', reasons=[reason])
        assert result['pending_reason'] == 'obligations'
        assert result['next_review_at'] == '2026-11-18T00:00:00Z'
        assert ack(store, 'orders', revision, 'failed') == result
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    restarted = Store(path, store.authority, store.responsible_operator)
    try:
        with pytest.raises(ValueError, match='invalid'):
            ack(restarted, 'orders', 4, terminal)
        with pytest.raises(ValueError, match='invalid'):
            ack(restarted, 'orders', 4, 'retained', reasons=['audit' if reason != 'audit' else 'custody'], next_review_at='2026-11-18T00:00:00Z')
        assert restarted.lookup('request-1', *ARGS, NOW)['domains']['orders']['reasons'] == [reason]
        result = ack(restarted, 'orders', 4, terminal, obligations_closed_at='2026-11-17T00:00:00Z')
        assert result['domains']['orders'] == dict(state=terminal, reasons=[])
    finally:
        restarted.close()


def test_completed_export_cannot_be_reassembled_after_cleanup(store):
    start(store, 'export')
    for index, domain in enumerate(DOMAINS):
        ack(store, domain, index + 1, 'exported')
    store.assemble('request-1', *ARGS, 10, [dict(ref='f', size=1)], NOW)
    expiry = NOW + timedelta(hours=24)
    failed = store.remove_file_ack('request-1', *ARGS, 'f', False, expiry)
    assert failed['state'] == 'partial'
    assert not failed['export_available']
    complete = store.remove_file_ack('request-1', *ARGS, 'f', True, expiry)
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    restarted = Store(path, store.authority, store.responsible_operator)
    try:
        for ref in ('f', 'different-file'):
            with pytest.raises(ValueError, match='conflict'):
                restarted.assemble('request-1', *ARGS, complete['revision'], [dict(ref=ref, size=1)], expiry)
        assert restarted.expired_files('request-1', *ARGS, expiry) == []
        assert restarted.remove_file_ack('request-1', *ARGS, 'f', True, expiry) == complete
        assert not restarted.lookup('request-1', *ARGS, expiry)['export_available']
    finally:
        restarted.close()
