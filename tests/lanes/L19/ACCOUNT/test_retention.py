import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('retention', ROOT/'services/identity/modules/private-seller/retention.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
PHOTO = dict(id='test-photo', listing_id='test-listing', subject_id='test-seller', challenge_id='test-challenge')
FACTS = dict(photo_id='test-photo', listing_id='test-listing', subject_id='test-seller', challenge_id='test-challenge',
             final_review_at=NOW-timedelta(days=30), reviewer_id='test-reviewer', assignment_revision=1, active_case=False)


def test_exact_removal_boundary_and_active_hold():
    assert m.removal_due(PHOTO, FACTS, NOW)
    assert not m.removal_due(PHOTO, FACTS, NOW-timedelta(microseconds=1))
    assert not m.removal_due(PHOTO, dict(FACTS, active_case=True), NOW)
    assert not m.removal_due(PHOTO, dict(FACTS, final_review_at=None), NOW)


@pytest.mark.parametrize('change', [dict(active_case=None), dict(challenge_id='test-other'), dict(reviewer_id='test-seller'),
                                    dict(assignment_revision=0), dict(final_review_at=NOW+timedelta(seconds=1))])
def test_unknown_denied_and_mismatched_facts_never_remove(change):
    with pytest.raises(Exception) as caught:
        m.removal_due(PHOTO, dict(FACTS, **change), NOW)
    assert caught.value.code == 'unavailable'


@pytest.mark.asyncio
async def test_hold_release_removes_due_photo_once():
    class Store:
        photo = PHOTO
        calls = []
        async def fetchrow(self, *args): return self.photo
        async def execute(self, sql, *args):
            self.calls.append((sql, args))
            if sql.startswith('DELETE'): self.photo = None
    store = Store()
    assert not await m.reconcile_photo(store, 'test-photo', dict(FACTS, active_case=True), NOW)
    assert store.calls[-1][1][-1] is True
    assert await m.reconcile_photo(store, 'test-photo', FACTS, NOW)
    assert not await m.reconcile_photo(store, 'test-photo', FACTS, NOW)
    assert sum(sql.startswith('DELETE') for sql, _ in store.calls) == 1
