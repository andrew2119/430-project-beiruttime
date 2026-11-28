import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location('saved_watch_store', ROOT / 'services/communications/modules/saved-watches/store.py')
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
Store, Watch, Failure = module.Store, module.Watch, module.Failure
FIXTURE = json.loads((ROOT / 'packages/contracts-comms/saved-watches/fixtures.json').read_text())


class Provider:
    def __init__(self):
        self.events = []
        self._current = Watch(**FIXTURE['source'])
        self.allowed = True
        self.timeout = False
        self.lost = False
        self.notices = {}

    @property
    def current(self):
        return self._current

    @current.setter
    def current(self, value):
        old = self._current
        if value.revision > old.revision:
            changes = []
            if value.price_minor != old.price_minor:
                changes.append('price')
            if value.bid_sequence > old.bid_sequence:
                changes.append('bid')
            if value.status == 'sold' and old.status != 'sold':
                changes.append('sold')
            for kind in changes:
                if any(event['event_id'] == f'{kind}-{value.revision}' for event in self.events):
                    continue
                self.events.append(dict(event_id=f'{kind}-{value.revision}', watch_id=value.watch_id,
                                        kind=kind, revision=value.revision,
                                        occurred_at=value.occurred_at, sample=value.sample))
        self._current = value

    def occurrences(self, watch_id, after, through, limit):
        items = [{**event, 'watch_id': watch_id}
                 for event in self.events if after < event['revision'] <= through]
        if len(items) > limit:
            raise Failure('unavailable')
        return dict(through_revision=through, items=items)

    def recovery_assignment(self, notice_id):
        return ('operator-1', 'operator-2')

    def authorize_recovery(self, actor, operator, notice_id):
        return self.allowed and actor == operator

    def authorize(self, actor, owner):
        return self.allowed and actor == owner

    def watch(self, watch_id):
        if self.timeout:
            raise TimeoutError
        return replace(self.current, watch_id=watch_id)

    def deliver(self, notice):
        self.notices.setdefault(notice['notice_id'], notice)
        if self.lost:
            raise TimeoutError


def command(operation='save-1', revision=0, saved=True, alerts=None):
    return dict(schema_version=module.VERSION, operation_id=operation, expected_revision=revision,
                saved=saved, alerts=alerts if alerts is not None else ['price', 'bid', 'ending', 'sold'])


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    store = Store(tmp_path / 'saved.db', provider)
    yield store, provider, tmp_path / 'saved.db'
    store.close()


def save(store, **kwargs):
    return store.save('buyer-1', 'buyer-1', 'watch-1', command(**kwargs))


def test_contract_fixture_and_restart(setup):
    store, provider, path = setup
    assert save(store) == FIXTURE['success']
    reopened = Store(path, provider)
    assert save(reopened) == FIXTURE['success']
    assert reopened.lookup('buyer-1', 'buyer-1', 'save-1') == FIXTURE['success']
    assert reopened.listing('buyer-1', 'buyer-1')['total'] == 1
    reopened.close()


@pytest.mark.parametrize('method,args', [
    ('listing', ()), ('lookup', ('save-1',)), ('save', ('watch-1', command()))])
def test_cross_account_denied(setup, method, args):
    store, _, _ = setup
    with pytest.raises(Failure, match='denied'):
        getattr(store, method)('buyer-2', 'buyer-1', *args)


def test_revocation_applies_to_retries(setup):
    store, provider, _ = setup
    save(store)
    provider.allowed = False
    with pytest.raises(Failure, match='denied'):
        save(store)


def test_stale_and_operation_conflict(setup):
    store, _, _ = setup
    save(store)
    with pytest.raises(Failure, match='stale'):
        save(store, operation='save-2')
    with pytest.raises(Failure, match='conflict'):
        save(store, saved=False)
    assert store.listing('buyer-1', 'buyer-1')['items'][0]['revision'] == 1


@pytest.mark.parametrize('status', ['sold', 'unavailable'])
def test_unavailable_saved_watch_remains_labeled(setup, status):
    store, provider, _ = setup
    save(store)
    provider.current = replace(provider.current, status=status, revision=4)
    item = store.listing('buyer-1', 'buyer-1')['items'][0]
    assert item['status'] == status and item['saved']


def test_timeout_is_not_success_and_retry_is_stable(setup):
    store, provider, _ = setup
    provider.timeout = True
    with pytest.raises(TimeoutError):
        save(store)
    assert store.lookup('buyer-1', 'buyer-1', 'save-1') is None
    provider.timeout = False
    save(store)
    provider.timeout = True
    assert store.listing('buyer-1', 'buyer-1')['items'][0]['status'] == 'unavailable'


@pytest.mark.parametrize('at,count', [('11:29:59', 0), ('11:30:00', 1), ('11:30:01', 1), ('12:00:00', 0), ('12:00:01', 0)])
def test_fixed_end_boundaries(setup, at, count):
    store, provider, _ = setup
    save(store)
    now = '2026-11-17T' + at + 'Z'
    store.observe('watch-1', now)
    store.dispatch(now)
    assert len(provider.notices) == count


@pytest.mark.parametrize('change', [dict(cancelled=True), dict(status='unavailable'), dict(scheduled_end='2026-11-17T13:00:00Z')])
def test_cancellation_withdrawal_and_extension_invalidate_ending(setup, change):
    store, provider, _ = setup
    save(store)
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    provider.current = replace(provider.current, revision=4, **change)
    store.dispatch('2026-11-17T11:30:01Z')
    assert not provider.notices


def test_actual_changes_deduplicate_after_lost_delivery_and_restart(setup):
    store, provider, path = setup
    save(store)
    store.observe('watch-1', '2026-11-17T10:00:00Z')
    provider.current = replace(provider.current, revision=4, price_minor=499000, bid_sequence=1)
    store.observe('watch-1', '2026-11-17T10:01:00Z')
    provider.lost = True
    assert store.dispatch('2026-11-17T10:01:01Z')['pending'] > 0
    provider.lost = False
    reopened = Store(path, provider)
    reopened.dispatch('2026-11-17T10:01:02Z')
    reopened.observe('watch-1', '2026-11-17T10:01:03Z')
    reopened.dispatch('2026-11-17T10:01:04Z')
    assert sorted(n['kind'] for n in provider.notices.values()) == ['bid', 'price']
    assert all(not n['required'] for n in provider.notices.values())
    reopened.close()


def test_required_outbid_is_separate(setup):
    store, provider, _ = setup
    save(store, alerts=[])
    store.observe('watch-1', '2026-11-17T10:00:00Z')
    provider.current = replace(provider.current, revision=4, bid_sequence=1)
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    store.dispatch('2026-11-17T11:30:00Z')
    assert not provider.notices
    assert 'outbid' not in module.KINDS


def test_removed_and_changed_preferences_suppress_queued_notices(setup):
    store, provider, _ = setup
    save(store)
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    save(store, operation='remove-1', revision=1, saved=False, alerts=[])
    store.dispatch('2026-11-17T11:30:01Z')
    assert not provider.notices
    assert store.listing('buyer-1', 'buyer-1')['total'] == 0


def test_stale_canonical_revision_denied(setup):
    store, provider, _ = setup
    store.observe('watch-1', '2026-11-17T10:00:00Z')
    provider.current = replace(provider.current, revision=2)
    with pytest.raises(Failure, match='stale'):
        store.observe('watch-1', '2026-11-17T10:00:01Z')


@pytest.mark.parametrize('price', [1.5, True, -1, float('inf'), 9007199254740992])
def test_money_validation(setup, price):
    store, provider, _ = setup
    provider.current = replace(provider.current, price_minor=price)
    with pytest.raises(Failure, match='unavailable'):
        save(store)


def test_real_pagination_with_server_total(setup):
    _, provider, _ = setup
    store = Store(':memory:', provider)
    for index in range(1000):
        store.save('buyer-1', 'buyer-1', f'watch-{index:04}', command(operation=f'save-{index}'))
    pages = [store.listing('buyer-1', 'buyer-1', offset, 50) for offset in range(0, 1000, 50)]
    assert all(page['total'] == 1000 for page in pages)
    assert len({item['watch_id'] for page in pages for item in page['items']}) == 1000
    with pytest.raises(Failure, match='invalid'):
        store.listing('buyer-1', 'buyer-1', limit=1000)
    store.close()


def test_ending_survives_ordinary_bid_revision_with_immutable_retry(setup):
    store, provider, _ = setup
    save(store)
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    provider.current = replace(provider.current, revision=4, bid_sequence=1)
    store.observe('watch-1', '2026-11-17T11:30:01Z')
    provider.lost = True
    assert store.dispatch('2026-11-17T11:30:02Z')['pending'] > 0
    ending = next(n for n in provider.notices.values() if n['kind'] == 'ending')
    assert ending['save_revision'] == 1
    assert ending['source_revision'] == 3
    assert ending['scheduled_end'] == '2026-11-17T12:00:00Z'
    provider.current = replace(provider.current, revision=5, bid_sequence=2)
    provider.lost = False
    store.dispatch('2026-11-17T11:30:03Z')
    assert len([n for n in provider.notices.values() if n['kind'] == 'ending']) == 1
    assert next(n for n in provider.notices.values() if n['kind'] == 'ending') == ending


def test_remove_and_resave_uses_owner_private_tombstone(setup):
    store, _, _ = setup
    save(store)
    save(store, operation='remove-1', revision=1, saved=False)
    current = store.record('buyer-1', 'buyer-1', 'watch-1')
    assert current['revision'] == 2 and not current['saved']
    assert store.record('buyer-2', 'buyer-2', 'watch-1')['revision'] == 0
    assert save(store, operation='resave-1', revision=current['revision'])['revision'] == 3


def test_old_available_source_cannot_restore_sold_label(setup):
    store, provider, _ = setup
    save(store)
    initial = provider.current
    provider.current = replace(initial, revision=4, status='sold')
    store.observe('watch-1', '2026-11-17T10:00:00Z')
    provider.current = initial
    assert store.listing('buyer-1', 'buyer-1')['items'][0]['status'] == 'unavailable'


@pytest.mark.parametrize('at', ['2026-11-17T11:30:00', '2026-11-17T13:30:00+02:00', 'invalid'])
def test_non_utc_instant_denied(setup, at):
    store, _, _ = setup
    with pytest.raises(Failure, match='invalid'):
        store.observe('watch-1', at)


def test_denied_first_recipient_does_not_starve_later_recipient(setup):
    store, provider, _ = setup
    save(store)
    store.save('buyer-2', 'buyer-2', 'watch-1', command(operation='second'))
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    provider.authorize = lambda actor, owner: actor == owner and owner != 'buyer-1'
    assert store.dispatch('2026-11-17T11:30:01Z', limit=1)['pending'] == 1
    assert store.dispatch('2026-11-17T11:30:02Z', limit=1)['delivered'] == 1
    assert [n['owner_id'] for n in provider.notices.values()] == ['buyer-2']
    for second in range(3, 7):
        result = store.dispatch(f'2026-11-17T11:30:0{second}Z', limit=1)
    assert result['held'] == 1
    assert result['next_actor'] == 'communications_support'
    assert store.dispatch('2026-11-17T11:30:07Z')['pending'] == 0


def test_alert_uses_canonical_occurrence_not_poll_time(setup):
    store, provider, _ = setup
    save(store)
    provider.current = replace(provider.current, revision=4, price_minor=499000,
                               occurred_at='2026-11-17T10:01:00Z')
    store.observe('watch-1', '2026-11-17T11:00:00Z')
    store.dispatch('2026-11-17T11:01:00Z')
    notice = next(iter(provider.notices.values()))
    assert notice['occurred_at'] == '2026-11-17T10:01:00Z'
    assert notice['sample'] is True


def test_ending_uses_fixed_due_instant(setup):
    store, provider, _ = setup
    save(store)
    store.observe('watch-1', '2026-11-17T11:45:00Z')
    store.dispatch('2026-11-17T11:46:00Z')
    assert module.instant(next(iter(provider.notices.values()))['occurred_at']) == module.instant('2026-11-17T11:30:00Z')


def test_list_watermark_survives_restart_without_consuming_price_change(setup):
    store, provider, path = setup
    save(store)
    initial = provider.current
    provider.current = replace(initial, revision=4, price_minor=499000)
    assert store.listing('buyer-1', 'buyer-1')['items'][0]['price_minor'] == 499000
    reopened = Store(path, provider)
    provider.current = initial
    assert reopened.listing('buyer-1', 'buyer-1')['items'][0]['status'] == 'unavailable'
    provider.current = replace(initial, revision=4, price_minor=499000)
    reopened.observe('watch-1', '2026-11-17T10:00:00Z')
    reopened.dispatch('2026-11-17T10:00:01Z')
    assert [n['kind'] for n in provider.notices.values()] == ['price']
    reopened.close()


def test_list_sold_watermark_cannot_regress(setup):
    store, provider, _ = setup
    save(store)
    initial = provider.current
    provider.current = replace(initial, revision=4, status='sold')
    assert store.listing('buyer-1', 'buyer-1')['items'][0]['status'] == 'sold'
    provider.current = initial
    assert store.listing('buyer-1', 'buyer-1')['items'][0]['status'] == 'unavailable'


@pytest.mark.parametrize('lost', [False, True])
def test_ending_survives_preference_update_with_original_payload(setup, lost):
    store, provider, _ = setup
    save(store)
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    provider.lost = lost
    if lost:
        store.dispatch('2026-11-17T11:30:01Z')
    save(store, operation='preferences-2', revision=1, alerts=['ending'])
    provider.lost = False
    assert store.dispatch('2026-11-17T11:30:02Z')['delivered'] == 1
    store.observe('watch-1', '2026-11-17T11:30:03Z')
    store.dispatch('2026-11-17T11:30:04Z')
    assert len(provider.notices) == 1
    assert store.record('buyer-1', 'buyer-1', 'watch-1')['ending_since_revision'] == 1
    assert next(iter(provider.notices.values()))['save_revision'] == 1


def test_disabling_then_enabling_does_not_restore_retired_ending(setup):
    store, provider, _ = setup
    save(store)
    store.observe('watch-1', '2026-11-17T11:30:00Z')
    save(store, operation='disable', revision=1, alerts=[])
    save(store, operation='enable', revision=2, alerts=['ending'])
    store.dispatch('2026-11-17T11:30:01Z')
    assert not provider.notices


@pytest.mark.parametrize('kind', ['price', 'bid', 'sold'])
@pytest.mark.parametrize('lost', [False, True])
def test_newer_compatible_revision_preserves_occurrence_after_restart(setup, kind, lost):
    store, provider, path = setup
    save(store, alerts=[kind])
    changes = {'price': dict(price_minor=499000), 'bid': dict(bid_sequence=1),
               'sold': dict(status='sold')}
    provider.current = replace(provider.current, revision=4,
                               occurred_at='2026-11-17T10:01:00Z', **changes[kind])
    store.observe('watch-1', '2026-11-17T10:02:00Z')
    provider.lost = lost
    if lost:
        assert store.dispatch('2026-11-17T10:02:01Z')['pending'] == 1
    provider.current = replace(provider.current, revision=5, title='Updated public title',
                               occurred_at='2026-11-17T10:03:00Z')
    provider.lost = False
    reopened = Store(path, provider)
    assert reopened.dispatch('2026-11-17T10:04:00Z')['delivered'] == 1
    reopened.observe('watch-1', '2026-11-17T10:04:01Z')
    reopened.dispatch('2026-11-17T10:04:02Z')
    assert len(provider.notices) == 1
    notice = next(iter(provider.notices.values()))
    assert notice['kind'] == kind and notice['source_revision'] == 4
    assert notice['occurred_at'] == '2026-11-17T10:01:00Z'
    reopened.close()


@pytest.mark.parametrize('kind', ['price', 'bid'])
@pytest.mark.parametrize('changes', [dict(status='unavailable'), dict(cancelled=True)])
def test_newer_incompatible_state_suppresses_change_occurrence(setup, kind, changes):
    store, provider, _ = setup
    save(store, alerts=[kind])
    provider.current = replace(provider.current, revision=4, price_minor=499000, bid_sequence=1)
    store.observe('watch-1', '2026-11-17T10:01:00Z')
    provider.current = replace(provider.current, revision=5, **changes)
    assert store.dispatch('2026-11-17T10:02:00Z')['delivered'] == 0
    assert not provider.notices


@pytest.mark.parametrize('kind', ['price', 'bid', 'sold'])
@pytest.mark.parametrize('lost', [False, True])
def test_continuous_alert_survives_preferences_and_restart(setup, kind, lost):
    store, provider, path = setup
    save(store)
    changes = {'price': dict(price_minor=499000), 'bid': dict(bid_sequence=1),
               'sold': dict(status='sold')}
    provider.current = replace(provider.current, revision=4, **changes[kind])
    store.observe('watch-1', '2026-11-17T10:01:00Z')
    provider.lost = lost
    if lost:
        store.dispatch('2026-11-17T10:01:01Z')
    save(store, operation='preferences', revision=1, alerts=[kind])
    provider.lost = False
    reopened = Store(path, provider)
    assert reopened.dispatch('2026-11-17T10:01:02Z')['delivered'] == 1
    assert len(provider.notices) == 1
    assert next(iter(provider.notices.values()))['save_revision'] == 1
    reopened.close()


@pytest.mark.parametrize('kind', ['price', 'bid'])
@pytest.mark.parametrize('advance', [False, True])
def test_new_subscription_excludes_earlier_activity_without_consuming_old_change(setup, kind, advance):
    store, provider, path = setup
    save(store, alerts=[kind])
    provider.current = replace(provider.current, revision=4, price_minor=499000, bid_sequence=1)
    store.save('buyer-2', 'buyer-2', 'watch-1', command(operation='second', alerts=[kind]))
    if advance:
        provider.current = replace(provider.current, revision=5, title='Updated title')
    reopened = Store(path, provider)
    reopened.observe('watch-1', '2026-11-17T10:01:00Z')
    reopened.dispatch('2026-11-17T10:01:01Z')
    assert [n['owner_id'] for n in provider.notices.values()] == ['buyer-1']
    provider.current = replace(provider.current, revision=6, price_minor=498000, bid_sequence=2)
    reopened.observe('watch-1', '2026-11-17T10:02:00Z')
    reopened.dispatch('2026-11-17T10:02:01Z')
    assert len(provider.notices) == 3
    reopened.close()


@pytest.mark.parametrize('kind', ['price', 'bid', 'sold'])
def test_disabled_subscription_cannot_restore_retired_occurrence(setup, kind):
    store, provider, _ = setup
    save(store, alerts=[kind])
    provider.current = replace(provider.current, revision=4, price_minor=499000,
                               bid_sequence=1, status='sold' if kind == 'sold' else 'available')
    store.observe('watch-1', '2026-11-17T10:01:00Z')
    save(store, operation='disable', revision=1, alerts=[])
    save(store, operation='enable', revision=2, alerts=[kind])
    store.dispatch('2026-11-17T10:01:01Z')
    assert not provider.notices


def test_retained_occurrences_survive_title_edit_and_price_round_trip(setup):
    store, provider, path = setup
    save(store, alerts=['price'])
    initial = provider.current.price_minor
    provider.current = replace(provider.current, revision=4, price_minor=499000,
                               occurred_at='2026-11-17T10:01:00Z')
    provider.current = replace(provider.current, revision=5, title='Changed title',
                               occurred_at='2026-11-17T10:02:00Z')
    provider.current = replace(provider.current, revision=6, price_minor=initial,
                               occurred_at='2026-11-17T10:03:00Z')
    reopened = Store(path, provider)
    reopened.observe('watch-1', '2026-11-17T10:04:00Z')
    reopened.dispatch('2026-11-17T10:04:01Z')
    notices = sorted(provider.notices.values(), key=lambda notice: notice['source_revision'])
    assert [(n['source_revision'], n['occurred_at']) for n in notices] == [
        (4, '2026-11-17T10:01:00Z'), (6, '2026-11-17T10:03:00Z')]
    reopened.observe('watch-1', '2026-11-17T10:05:00Z')
    reopened.dispatch('2026-11-17T10:05:01Z')
    assert len(provider.notices) == 2
    reopened.close()


def test_incomplete_occurrence_read_does_not_consume_cursor(setup):
    store, provider, _ = setup
    save(store, alerts=['price'])
    provider.current = replace(provider.current, revision=4, price_minor=499000)
    original = provider.occurrences
    provider.occurrences = lambda *args: dict(through_revision=3, items=[])
    with pytest.raises(Failure, match='unavailable'):
        store.observe('watch-1', '2026-11-17T10:00:00Z')
    provider.occurrences = original
    store.observe('watch-1', '2026-11-17T10:00:01Z')
    assert store.dispatch('2026-11-17T10:00:02Z')['delivered'] == 1


def hold_notice(store, provider):
    save(store, alerts=['price'])
    provider.current = replace(provider.current, revision=4, price_minor=499000)
    store.observe('watch-1', '2026-11-17T10:00:00Z')
    provider.lost = True
    for second in range(5):
        store.dispatch(f'2026-11-17T10:01:0{second}Z')
    return next(iter(provider.notices))


@pytest.mark.parametrize('elapsed,action,operator', [
    ('2026-11-18T10:01:03Z', 'review_delivery', 'operator-1'),
    ('2026-11-18T10:01:04Z', 'response_overdue', 'operator-1'),
    ('2026-11-18T10:01:05Z', 'response_overdue', 'operator-1'),
    ('2026-11-19T10:01:03Z', 'response_overdue', 'operator-1'),
    ('2026-11-19T10:01:04Z', 'escalated_review', 'operator-2'),
    ('2026-11-20T10:01:04Z', 'escalated_review', 'operator-2')])
def test_durable_held_deadlines_and_escalation(setup, elapsed, action, operator):
    store, provider, path = setup
    notice = hold_notice(store, provider)
    reopened = Store(path, provider)
    reopened.dispatch(elapsed)
    recovery = reopened.recovery(operator, notice)
    assert recovery['next_action'] == action and recovery['operator'] == operator
    assert recovery['response_due'] == '2026-11-18T10:01:04+00:00'
    assert recovery['escalate_at'] == '2026-11-19T10:01:04+00:00'
    with pytest.raises(Failure, match='denied'):
        reopened.recovery('buyer-1', notice)
    reopened.close()


def test_reconciliation_is_authorized_stable_and_retains_notice(setup):
    store, provider, path = setup
    notice = hold_notice(store, provider)
    args = ('operator-1', notice, 'reconcile-1', 1, '2026-11-17T11:00:00Z')
    with pytest.raises(Failure, match='denied'):
        store.reconcile('buyer-1', *args[1:])
    result = store.reconcile(*args)
    reopened = Store(path, provider)
    assert reopened.reconcile(*args) == result
    with pytest.raises(Failure, match='conflict'):
        reopened.reconcile(*args[:-1], '2026-11-17T11:01:00Z')
    with pytest.raises(Failure, match='stale'):
        reopened.reconcile('operator-1', notice, 'reconcile-2', 1, args[-1])
    provider.allowed = False
    with pytest.raises(Failure, match='denied'):
        reopened.reconcile(*args)
    provider.allowed = True
    provider.lost = False
    assert reopened.dispatch('2026-11-17T11:02:00Z')['delivered'] == 1
    assert list(provider.notices) == [notice]
    assert reopened.recovery('operator-1', notice)['state'] == 'resolved'
    reopened.close()


def test_occurrence_overflow_fails_closed_without_advancing_observation(setup):
    store, provider, _ = setup
    save(store, alerts=['price'])
    for revision in range(4, 205):
        provider.current = replace(provider.current, revision=revision, price_minor=500000 - revision)
    with pytest.raises(Failure, match='unavailable'):
        store.observe('watch-1', '2026-11-17T10:00:00Z')
    assert store.db.execute("SELECT revision FROM l22_sources WHERE watch='watch-1'").fetchone()[0] == 3
    assert store.dispatch('2026-11-17T10:00:01Z')['delivered'] == 0
