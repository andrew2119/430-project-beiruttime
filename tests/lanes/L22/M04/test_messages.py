import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('private_messages', ROOT / 'services/communications/modules/messages/domain.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Store, Denied = module.Store, module.Denied
NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def snapshot(**changes):
    return dict(id='thread-1', kind='listing', subject_id='listing-1', watch_id='watch-1', organization_id=None,
                source_revision=1, quote_revision=None, policy_revision=1, original_work_id=None,
                active_support=False, paid_held=False, members=[{'actor_id': actor, 'joined_at': (NOW-timedelta(days=1)).isoformat(), 'left_at': None} for actor in ('buyer', 'seller')]) | changes


def facts(actor='buyer', **changes):
    return dict(state='authorized', actor_id=actor, organization_id=None, thread_id='thread-1', subject_id='listing-1',
                watch_id='watch-1', source_revision=1, quote_revision=None, policy_revision=1, current_member=True,
                paid_held=False, active_support=False) | changes


def command(kind='send', **changes):
    return dict(operation_id='operation-1', expected_revision=1, source_revision=1, quote_revision=None,
                policy_revision=1, kind=kind, body='A watch question') | changes


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / 'messages.db')
    result.provision(snapshot())
    return result


def send(store, body=None, actor='buyer', authority=None, now=NOW):
    return store.command('thread-1', actor, None, authority or facts(actor), now, body or command())


def test_lost_reply_retry_restart_and_private_outbox(store):
    result = send(store)
    reopened = Store(store.path)
    assert reopened.lookup('thread-1', 'buyer', None, facts(), NOW, 'operation-1') == result
    assert send(reopened) == result
    page = reopened.read('thread-1', 'seller', None, facts('seller'), NOW)
    assert page['total'] == page['unread'] == 1
    with reopened.tx() as db:
        events = db.execute('SELECT event FROM l22_outbox').fetchall()
    assert len(events) == 1
    assert 'question' not in events[0]['event']


def test_conflicting_retry_and_stale(store):
    send(store)
    with pytest.raises(Denied, match='operation_conflict'):
        send(store, command(body='Changed private text'))
    with pytest.raises(Denied, match='revision'):
        send(store, command(operation_id='new-operation'))


@pytest.mark.parametrize('change', [{'actor_id': 'other'}, {'organization_id': 'other'}, {'watch_id': 'other'},
                                   {'subject_id': 'other'}, {'current_member': False}, {'source_revision': 2},
                                   {'state': 'denied'}, {'state': 'unavailable'}])
def test_wrong_current_scope_denies(store, change):
    send(store)
    with pytest.raises(Denied):
        store.read('thread-1', 'buyer', None, facts(**change), NOW)
    with pytest.raises(Denied):
        send(store, authority=facts(**change))
    with pytest.raises(Denied):
        store.lookup('thread-1', 'buyer', None, facts(**change), NOW, 'operation-1')


@pytest.mark.parametrize('offset,allowed', [(-1, True), (0, False), (1, False)])
def test_removal_before_equal_after(store, offset, allowed):
    source = snapshot()
    source['members'][0]['left_at'] = NOW.isoformat()
    store.provision(source)
    time = NOW + timedelta(microseconds=offset)
    if allowed:
        assert send(store, command(expected_revision=2), now=time)['state'] == 'accepted'
    else:
        with pytest.raises(Denied, match='membership'):
            send(store, now=time)


@pytest.mark.parametrize('offset,allowed', [(-1, False), (0, True), (1, True)])
def test_entry_before_equal_after(store, offset, allowed):
    source = snapshot()
    source['members'][0]['joined_at'] = NOW.isoformat()
    store.provision(source)
    if allowed:
        send(store, command(expected_revision=2), now=NOW+timedelta(microseconds=offset))
    else:
        with pytest.raises(Denied):
            send(store, command(expected_revision=2), now=NOW+timedelta(microseconds=offset))


def test_rejoined_member_cannot_read_old_interval(store):
    send(store)
    source = snapshot(source_revision=2)
    source['members'][0]['joined_at'] = (NOW+timedelta(seconds=1)).isoformat()
    store.provision(source)
    page = store.read('thread-1', 'buyer', None, facts(source_revision=2), NOW+timedelta(seconds=2))
    assert page['items'] == []


@pytest.mark.parametrize('text', ['name@example.test', '+961 71 123 456', '٠٧١ ١٢٣ ٤٥٦', 'name at example dot test', 'https://example.test/private'])
@pytest.mark.parametrize('kind', ['listing', 'order', 'business'])
def test_contact_preview_correction_and_appeal(store, text, kind):
    store = Store(Path(store.path).with_name(f'contacts-{kind}.db'))
    store.provision(snapshot(kind=kind))
    send(store, command(body=text))
    page = store.read('thread-1', 'buyer', None, facts(), NOW)
    assert page['items'][0]['correction_required']
    assert text not in page['items'][0]['preview']
    result = send(store, command('appeal', expected_revision=2, operation_id='appeal-1', sequence=1, body='This was a reference number.'))
    assert result['state'] == 'accepted'
    with store.tx() as db:
        assert db.execute('SELECT state FROM l22_reports').fetchone()[0] == 'pending'


def test_active_support_cannot_be_abandoned(store):
    source = snapshot(active_support=True, source_revision=2)
    store.provision(source)
    with pytest.raises(Denied, match='support_required'):
        send(store, command('block', source_revision=2, expected_revision=2, target='seller'), authority=facts(source_revision=2, active_support=True))
    assert send(store, command(source_revision=2, expected_revision=2), authority=facts(source_revision=2, active_support=True))['state'] == 'accepted'


def test_block_read_write_and_unblock(store):
    send(store, command('block', target='seller'))
    with pytest.raises(Denied, match='blocked'):
        store.read('thread-1', 'seller', None, facts('seller'), NOW)
    with pytest.raises(Denied, match='blocked'):
        send(store, command(expected_revision=2), actor='seller')
    send(store, command('unblock', target='seller', expected_revision=2, operation_id='unblock-1'))
    send(store, command(expected_revision=3, operation_id='send-after-unblock'))


def test_unread_marker_separate_and_monotonic(store):
    send(store)
    send(store, command('read', expected_revision=2, operation_id='read-1', sequence=1), actor='seller')
    assert store.read('thread-1', 'seller', None, facts('seller'), NOW)['unread'] == 0
    assert store.read('thread-1', 'seller', None, facts('seller'), NOW)['total'] == 1


def test_delivery_needs_current_payment(store):
    with pytest.raises(Denied, match='payment_required'):
        send(store, command('delivery', body='Private delivery details'))
    store.provision(snapshot(paid_held=True, source_revision=2))
    send(store, command('delivery', expected_revision=2, source_revision=2, body='Private delivery details'), authority=facts(paid_held=True, source_revision=2))
    page = store.read('thread-1', 'seller', None, facts('seller', paid_held=True, source_revision=2), NOW)
    assert 'Private delivery details' not in json.dumps(page)


def test_concurrent_identical_operation_one_message(store):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: send(store), range(2)))
    assert results[0] == results[1]
    assert store.read('thread-1', 'buyer', None, facts(), NOW)['total'] == 1


def test_thousand_rows_server_totals_and_boundaries(store):
    for number in range(1000):
        send(store, command(operation_id=f'message-{number}', expected_revision=number+1, body='ساعة watch ⌚ ' * 20))
    cursor, collected = 0, []
    while cursor is not None:
        page = store.read('thread-1', 'seller', None, facts('seller'), NOW, cursor, 50)
        assert page['total'] == 1000
        collected.extend(item['sequence'] for item in page['items'])
        cursor = page['next_cursor']
    assert collected == list(range(1, 1001))


@pytest.mark.parametrize('change', [{'body': 'x'*4001}, {'body': ''}, {'expected_revision': True}, {'source_revision': True}, {'policy_revision': True}, {'quote_revision': True}, {'kind': 'upload'}, {'sequence': -1, 'kind': 'read'}])
def test_bounds(store, change):
    with pytest.raises(Denied):
        send(store, command(**change))


def test_frozen_fixture_lost_response():
    fixtures = json.loads((ROOT / 'packages/contracts-comms/messages/fixtures.json').read_text())
    assert fixtures['synthetic']
    assert fixtures['success'] | {} == fixtures['lost_response']['lookup'] | {'operation_id': 'send-1'}


def test_buyer_and_selected_colleague_share_business_thread(store):
    source = snapshot(organization_id='business-1')
    source['members'][1]['organization_id'] = 'business-1'
    # A new record carries its immutable subject business separately from actor scope.
    source['id'] = 'business-thread'
    store.provision(source)
    buyer_facts = facts(thread_id='business-thread', subject_organization_id='business-1')
    colleague_facts = facts('seller', thread_id='business-thread', organization_id='business-1', subject_organization_id='business-1')
    store.command('business-thread', 'buyer', None, buyer_facts, NOW, command())
    assert store.read('business-thread', 'seller', 'business-1', colleague_facts, NOW)['total'] == 1
    with pytest.raises(Denied):
        store.read('business-thread', 'seller', 'business-2', colleague_facts | {'organization_id':'business-2'}, NOW)


def test_active_support_preserves_preexisting_block(store):
    send(store, command('block', target='seller'))
    store.provision(snapshot(active_support=True, source_revision=2))
    authority = facts(active_support=True, source_revision=2)
    assert store.read('thread-1', 'buyer', None, authority, NOW)['total'] == 0
    send(store, command(expected_revision=3, source_revision=2, operation_id='support-send'), authority=authority)
    store.provision(snapshot(active_support=False, source_revision=3))
    with pytest.raises(Denied, match='blocked'):
        store.read('thread-1', 'buyer', None, facts(source_revision=3), NOW)


def test_delivery_interval_privacy(store):
    store.provision(snapshot(paid_held=True, source_revision=2))
    authority = facts(paid_held=True, source_revision=2)
    send(store, command('delivery', body='Private address', expected_revision=2, source_revision=2), authority=authority)
    assert store.delivery('thread-1', 'seller', None, facts('seller', paid_held=True, source_revision=2), NOW)['items']
    updated = snapshot(paid_held=True, source_revision=3)
    updated['members'][1]['joined_at'] = (NOW+timedelta(seconds=1)).isoformat()
    store.provision(updated)
    assert store.delivery('thread-1', 'seller', None, facts('seller', paid_held=True, source_revision=3), NOW+timedelta(seconds=2))['items'] == []


@pytest.mark.parametrize('actor', ['buyer', 'seller'])
def test_delivery_block_and_active_support_exception(store, actor):
    store.provision(snapshot(paid_held=True, source_revision=2))
    authority = facts(paid_held=True, source_revision=2)
    send(store, command('delivery', body='Private address', expected_revision=2, source_revision=2), authority=authority)
    send(store, command('block', target='seller', operation_id='block-delivery', expected_revision=3, source_revision=2), authority=authority)
    with pytest.raises(Denied, match='blocked'):
        store.delivery('thread-1', actor, None, facts(actor, paid_held=True, source_revision=2), NOW)
    store.provision(snapshot(paid_held=True, active_support=True, source_revision=3))
    assert store.delivery('thread-1', actor, None, facts(actor, paid_held=True, active_support=True, source_revision=3), NOW)['items'] == [{'actor': 'buyer', 'value': 'Private address'}]
    store.provision(snapshot(paid_held=True, active_support=False, source_revision=4))
    with pytest.raises(Denied, match='blocked'):
        store.delivery('thread-1', actor, None, facts(actor, paid_held=True, source_revision=4), NOW)


@pytest.mark.parametrize('actor', ['buyer', 'seller'])
def test_block_gates_receipts_and_support_preserves_original_operation(store, actor):
    original = command()
    receipt = send(store, original, actor=actor)
    other = 'seller' if actor == 'buyer' else 'buyer'
    send(store, command('block', target=actor, expected_revision=2, operation_id='block-receipt'), actor=other)
    with pytest.raises(Denied, match='blocked'):
        store.lookup('thread-1', actor, None, facts(actor), NOW, original['operation_id'])
    with pytest.raises(Denied, match='blocked'):
        send(store, original, actor=actor)
    store.provision(snapshot(active_support=True, source_revision=2))
    authority = facts(actor, active_support=True, source_revision=2)
    assert store.lookup('thread-1', actor, None, authority, NOW, original['operation_id']) == receipt
    assert send(store, original, actor=actor, authority=authority) == receipt
    assert store.read('thread-1', actor, None, authority, NOW)['total'] == 1


@pytest.mark.parametrize('original, replacement', [('business-a', 'business-b'), (None, 'business-b'), ('business-a', None)])
def test_receipt_binds_original_organization_after_restart(store, original, replacement):
    def authorize(organization, revision):
        source = snapshot(source_revision=revision)
        source['members'][0]['organization_id'] = organization
        store.provision(source)
        return facts(organization_id=organization, source_revision=revision)

    authority = authorize(original, 2)
    body = command(expected_revision=2, source_revision=2)
    receipt = store.command('thread-1', 'buyer', original, authority, NOW, body)
    reopened = Store(store.path)
    assert reopened.lookup('thread-1', 'buyer', original, authority, NOW, body['operation_id']) == receipt
    assert reopened.command('thread-1', 'buyer', original, authority, NOW, body) == receipt
    changed = authorize(replacement, 3)
    reopened = Store(store.path)
    with pytest.raises(Denied, match='operation_conflict'):
        reopened.lookup('thread-1', 'buyer', replacement, changed, NOW, body['operation_id'])
    with pytest.raises(Denied, match='operation_conflict'):
        reopened.command('thread-1', 'buyer', replacement, changed, NOW, body)
    assert reopened.read('thread-1', 'buyer', replacement, changed, NOW)['total'] == 1


def test_unbound_retained_receipt_fails_closed(store):
    send(store)
    with store.tx() as db:
        db.execute('ALTER TABLE l22_receipts DROP COLUMN organization')
    reopened = Store(store.path)
    with pytest.raises(Denied, match='operation_conflict'):
        reopened.lookup('thread-1', 'buyer', None, facts(), NOW, 'operation-1')
    with pytest.raises(Denied, match='operation_conflict'):
        send(reopened)
    assert reopened.read('thread-1', 'buyer', None, facts(), NOW)['total'] == 1


def test_lost_block_reply_recovery_keeps_messages_private(store):
    send(store)
    body = command('block', target='seller', expected_revision=2, operation_id='block-lost')
    receipt = send(store, body)
    reopened = Store(store.path)
    assert reopened.lookup('thread-1', 'buyer', None, facts(), NOW, 'block-lost') == receipt
    assert send(reopened, body) == receipt
    with pytest.raises(Denied, match='operation_conflict'):
        send(reopened, body | {'target': 'other'})
    for actor in ('buyer', 'seller'):
        with pytest.raises(Denied, match='blocked'):
            reopened.read('thread-1', actor, None, facts(actor), NOW)
        with pytest.raises(Denied, match='blocked'):
            reopened.lookup('thread-1', actor, None, facts(actor), NOW, 'operation-1')
    with pytest.raises(Denied, match='blocked'):
        reopened.lookup('thread-1', 'seller', None, facts('seller'), NOW, 'block-lost')
    with pytest.raises(Denied):
        reopened.lookup('thread-1', 'buyer', None, facts(current_member=False), NOW, 'block-lost')
    send(reopened, command('unblock', target='seller', expected_revision=3, operation_id='recover-unblock'))
    assert reopened.read('thread-1', 'buyer', None, facts(), NOW)['total'] == 1
    with reopened.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM l22_receipts').fetchone()[0] == 3
