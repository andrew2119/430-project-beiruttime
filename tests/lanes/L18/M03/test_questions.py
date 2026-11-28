import asyncio
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[4] / 'services/communications/modules/listing-questions/model.py'
spec = importlib.util.spec_from_file_location('questions', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def run(value):
    return asyncio.run(value)


@pytest.fixture
def store(tmp_path):
    async def authority(actor, organization, listing):
        return dict(allowed=actor != 'revoked' and organization is None and listing == 'listing',
                    watch_id='watch', revision=3, seller_id='seller', can_answer=True, can_ask=True, can_report=True,
                    assigned_moderator=actor in ('moderator', 'buyer'), assigned_question_ids=['q'])
    async def assessment(text, kind):
        return 'abusive' not in text and 'private proof' not in text
    return m.Questions(tmp_path / 'questions.db', authority, assessment)


def body(kind='ask', **changes):
    return dict(operation_id='op', kind=kind, watch_id='watch', source_revision=3,
                expected_revision=0, question_id='q', text=' Is it original? ', **{}) | changes


def command(store, actor='buyer', **changes):
    return run(store.command(actor, None, 'listing', body(**changes)))


def test_seller_only_and_matching_is_suggestion(store):
    command(store)
    with pytest.raises(m.Rejected, match='denied'):
        command(store, operation_id='answer', kind='answer', expected_revision=1)
    command(store, 'seller', operation_id='answer', kind='answer', expected_revision=1, text='Yes')
    assert run(store.listing('buyer', None, 'listing', match='is IT original?'))['total'] == 1
    command(store, operation_id='second', question_id='q2')
    assert run(store.listing('buyer', None, 'listing'))['total'] == 2


@pytest.mark.parametrize('text', ['Email me at a@b.test', '+961 70 123 456', 'passport photo', 'رقم هاتف'])
def test_sensitive_never_public(store, text):
    assert command(store, text=text)['state'] == 'held'
    assert run(store.listing('buyer', None, 'listing'))['items'] == []
    assert text not in store.db.execute('SELECT payload FROM l18_outbox').fetchone()[0]


def test_restart_duplicate_conflict_and_revocation(store):
    first = command(store)
    restarted = m.Questions(store.db.execute('PRAGMA database_list').fetchone()[2], store.authority)
    assert command(restarted) == first
    assert run(restarted.lookup('buyer', None, 'listing', 'op')) == first
    with pytest.raises(m.Rejected, match='conflict'):
        command(store, text='Changed')
    with pytest.raises(m.Rejected, match='denied'):
        command(store, 'revoked')
    with pytest.raises(m.Rejected, match='denied'):
        run(store.lookup('seller', None, 'listing', 'op'))


def test_stale_report_independence_and_audit(store):
    with pytest.raises(m.Rejected, match='stale'):
        command(store, source_revision=2)
    command(store)
    command(store, kind='report', operation_id='report', expected_revision=1, text='Abusive')
    assert run(store.listing('buyer', None, 'listing'))['total'] == 0
    with pytest.raises(m.Rejected, match='denied'):
        command(store, kind='hide', operation_id='hide', expected_revision=2, text='Abusive')
    command(store, 'moderator', kind='hide', operation_id='hide', expected_revision=2, text='Abusive')
    assert store.db.execute('SELECT count(*) FROM l18_audit').fetchone()[0] == 1


@pytest.mark.parametrize('length,valid', [(0, False), (1, True), (2000, True), (2001, False)])
def test_text_boundaries(store, length, valid):
    if valid:
        command(store, text='x'*length)
    else:
        with pytest.raises(m.Rejected, match='invalid'):
            command(store, text='x'*length)


def test_timeout_fails_closed(store):
    async def unavailable(*args):
        raise TimeoutError
    store.authority = unavailable
    with pytest.raises(m.Rejected, match='unavailable'):
        command(store)
    assert store.db.execute('SELECT count(*) FROM l18_receipts').fetchone()[0] == 0


def test_thousand_rows_real_pagination(store):
    for i in range(1000):
        command(store, question_id=f'q{i:04}', operation_id=f'op{i}')
    pages = [run(store.listing('buyer', None, 'listing', page=i)) for i in range(50)]
    assert all(p['total'] == 1000 and len(p['items']) == 20 for p in pages)
    assert len({r['id'] for p in pages for r in p['items']}) == 1000


def test_exact_content_assessment_and_default_hold(store):
    assert command(store, text='abusive language')['state'] == 'held'
    assert command(store, operation_id='proof', question_id='proof', text='private proof enclosed')['state'] == 'held'
    store.assessment = None
    assert command(store, operation_id='missing', question_id='missing')['state'] == 'held'
    assert run(store.listing('buyer', None, 'listing'))['total'] == 0


def test_padding_cannot_bypass_bounds(store):
    with pytest.raises(m.Rejected, match='invalid'):
        command(store, text=' ' * 2000 + 'x')


def test_watch_rebinding_and_exact_assignment(store):
    command(store)
    original = store.authority
    async def changed(*args):
        scope = await original(*args)
        scope['watch_id'] = 'other'
        return scope
    store.authority = changed
    assert run(store.listing('buyer', None, 'listing'))['total'] == 0
    with pytest.raises(m.Rejected, match='stale'):
        command(store, 'seller', kind='answer', operation_id='answer', expected_revision=1, watch_id='other')
    store.authority = original
    with pytest.raises(m.Rejected, match='denied'):
        command(store, 'moderator', kind='hide', operation_id='hide', question_id='unassigned', expected_revision=1)


def test_private_appeal_and_independent_review(store):
    held = command(store, text='private proof enclosed')
    appealed = command(store, kind='appeal', operation_id='appeal', expected_revision=held['revision'], text='Please review the correction')
    assert appealed['revision'] == 2
    review = run(store.review('moderator', None, 'listing', 'q'))
    assert review['appeals'][0]['reason'] == 'Please review the correction'
    with pytest.raises(m.Rejected, match='denied'):
        run(store.review('buyer', None, 'listing', 'q'))
    with pytest.raises(m.Rejected, match='denied'):
        run(store.review('moderator', None, 'listing', 'unassigned'))
    assert run(store.listing('buyer', None, 'listing'))['total'] == 0
    assert 'proof' not in store.db.execute('SELECT payload FROM l18_outbox LIMIT 1').fetchone()[0]


def test_sensitive_seller_answer_quarantines_whole_thread(store):
    command(store)
    receipt = command(store, 'seller', kind='answer', operation_id='answer', expected_revision=1, text='Contact a@b.test')
    assert receipt['state'] == 'held'
    assert run(store.listing('buyer', None, 'listing'))['total'] == 0


def test_cross_organization_denies_and_rollback_is_atomic(store):
    with pytest.raises(m.Rejected, match='denied'):
        run(store.command('buyer', 'other', 'listing', body()))
    command(store)
    with pytest.raises(m.Rejected, match='stale'):
        command(store, operation_id='stale', kind='report', expected_revision=0)
    assert store.db.execute('SELECT count(*) FROM l18_receipts').fetchone()[0] == 1
    assert store.db.execute('SELECT count(*) FROM l18_outbox').fetchone()[0] == 1


def test_normalization_mixed_text_and_emoji(store):
    command(store, text='  الساعة ＡＢＣ 😀  ')
    command(store, 'seller', kind='answer', operation_id='answer', expected_revision=1, text='متوفرة Yes 😀')
    assert run(store.listing('buyer', None, 'listing', match='الساعة abc 😀'))['total'] == 1


def test_published_success_fixture_is_contract_identical(store):
    import json
    fixture_path = Path(__file__).resolve().parents[4] / 'packages/contracts-comms/listing-questions/fixtures.json'
    fixtures = json.loads(fixture_path.read_text())
    async def authority(actor, organization, listing):
        return dict(allowed=True, watch_id='sample-watch', revision=3, seller_id='sample-seller', can_ask=True)
    store.authority = authority
    result = run(store.command('sample-buyer', None, 'sample-listing', fixtures['command']))
    assert result == fixtures['success']
    assert run(store.lookup('sample-buyer', None, 'sample-listing', 'sample-operation')) == fixtures['success']


@pytest.mark.parametrize('scope', [None, {}, {'allowed': 'yes'}, {'allowed': True}, {'allowed': True, 'watch_id': 'watch', 'seller_id': 'seller', 'revision': True}])
def test_missing_current_facts_fail_closed(store, scope):
    async def missing(*args):
        return scope
    store.authority = missing
    with pytest.raises(m.Rejected, match='unavailable'):
        command(store)


@pytest.mark.parametrize('change', [{'can_answer': 'false'}, {'can_ask': 1}, {'can_report': []}, {'assigned_moderator': 'false'}, {'assigned_question_ids': 'question'}, {'assigned_question_ids': [1]}, {'assigned_question_ids': ['q']*1001}])
def test_malformed_permissions_fail_closed(store, change):
    original = store.authority
    async def malformed(*args):
        return await original(*args) | change
    store.authority = malformed
    with pytest.raises(m.Rejected, match='unavailable'):
        command(store)


def test_revoked_moderator_cannot_read_retained_assignment(store):
    command(store)
    original = store.authority
    async def revoked(*args):
        return await original(*args) | {'assigned_moderator': False}
    store.authority = revoked
    with pytest.raises(m.Rejected, match='denied'):
        run(store.review('moderator', None, 'listing', 'q'))


def test_question_reference_collision_is_stable_conflict(store):
    command(store)
    store.db.execute("UPDATE l18_questions SET listing='another-listing' WHERE id='q'")
    with pytest.raises(m.Rejected, match='conflict'):
        command(store, operation_id='collision')
    assert store.db.execute('SELECT count(*) FROM l18_receipts').fetchone()[0] == 1
    assert store.db.execute('SELECT count(*) FROM l18_outbox').fetchone()[0] == 1


def test_current_assignments_change_without_losing_moderation(store):
    before = run(store.listing('moderator', None, 'listing'))
    assert before['assigned_question_ids'] == ['q']
    original = store.authority
    async def reassigned(*args):
        return await original(*args) | {'assigned_question_ids': ['another']}
    store.authority = reassigned
    after = run(store.listing('moderator', None, 'listing'))
    assert after['can_moderate'] is True
    assert after['assigned_question_ids'] == ['another']
    assert run(store.listing(None, None, 'listing'))['assigned_question_ids'] == []
