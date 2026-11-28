import base64
import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('possession', ROOT / 'services/identity/modules/private-seller/possession.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
FACTS = dict(subject_id='seller-1', watch_id='watch-1', watch_revision=1, listing_revision=1, organization_id=None, seller_status='approved')


def issued():
    return m.issue('seller-1', 'listing-1', FACTS, None, 0, 'issue-0001', NOW, '123456', 'challenge-1')


def error(code, call):
    with pytest.raises(Exception) as caught:
        call()
    assert caught.value.code == code


def test_contract_fixture_and_exact_boundary():
    fixtures = json.loads((ROOT/'packages/contracts-identity/accounts/possession-fixtures.json').read_text())
    assert issued() == fixtures['issued']
    assert m.current(issued(), FACTS, NOW+timedelta(hours=24))['state'] == 'expired'
    error('proof_expired', lambda: m.submit('seller-1', FACTS, issued(), 1, 'challenge-1', '123456', 'submit-01', NOW+timedelta(hours=24)))


@pytest.mark.parametrize('digits', ['123456', '١٢٣٤٥٦', '۱۲۳۴۵۶'])
def test_single_use_submission(digits):
    proof = m.submit('seller-1', FACTS, issued(), 1, 'challenge-1', digits, 'submit-01', NOW+timedelta(hours=23))
    assert proof['state'] == 'pending'
    assert proof['next_actor'] == 'assigned_reviewer'
    error('proof_pending', lambda: m.submit('seller-1', FACTS, proof, 2, 'challenge-1', digits, 'submit-02', NOW))
    error('proof_pending', lambda: m.issue('seller-1', 'listing-1', FACTS, proof, 2, 'issue-002', NOW))


@pytest.mark.parametrize('change', [dict(subject_id='another'), dict(organization_id='business-2'), dict(seller_status='suspended'), dict(seller_status='pending')])
def test_current_permission_wrong_business_and_revocation(change):
    facts = dict(FACTS, **change)
    error('forbidden', lambda: m.issue('seller-1', 'listing-1', facts, None, 0, 'issue-0001', NOW))
    error('forbidden', lambda: m.submit('seller-1', facts, issued(), 1, 'challenge-1', '123456', 'submit-01', NOW))


@pytest.mark.parametrize('change', [dict(watch_id='watch-2'), dict(watch_revision=2), dict(listing_revision=2)])
def test_changed_identity_and_relisting_require_fresh_proof(change):
    facts = dict(FACTS, **change)
    assert m.current(issued(), facts, NOW)['state'] == 'stale'
    error('stale_proof', lambda: m.submit('seller-1', facts, issued(), 1, 'challenge-1', '123456', 'submit-01', NOW))
    fresh = m.issue('seller-1', 'listing-1', facts, issued(), 1, 'issue-0002', NOW)
    assert fresh['challenge_id'] != issued()['challenge_id']


def test_lost_response_duplicate_conflict_and_stale_retry():
    digest = m.request_digest('issue', {'expected_revision': 0})
    receipt = {'digest':digest, 'result':issued()}
    assert m.replay(receipt, digest, FACTS) == issued()
    error('operation_conflict', lambda: m.replay(receipt, 'changed', FACTS))
    error('stale_proof', lambda: m.replay(receipt, digest, dict(FACTS, listing_revision=2)))
    error('stale_proof', lambda: m.issue('seller-1', 'listing-1', FACTS, issued(), 0, 'issue-0002', NOW))


def test_wrong_code_wrong_challenge_and_reordered_submission():
    for challenge, code in [('challenge-2','123456'), ('challenge-1','000000'), ('challenge-1','abcdef'), ('challenge-1','😀😀😀😀😀😀'), ('challenge-1','١2۳a56')]:
        error('invalid_proof', lambda: m.submit('seller-1', FACTS, issued(), 1, challenge, code, 'submit-01', NOW))
    error('stale_proof', lambda: m.submit('seller-1', FACTS, None, 0, 'challenge-1', '123456', 'submit-01', NOW))


def test_expired_challenge_can_be_replaced():
    fresh = m.issue('seller-1', 'listing-1', FACTS, issued(), 1, 'issue-0002', NOW+timedelta(days=1))
    assert fresh['revision'] == 2
    assert fresh['expires_at'] != issued()['expires_at']


def test_private_photo_strips_metadata_and_rejects_invalid_bytes():
    source = io.BytesIO()
    meta = PngImagePlugin.PngInfo(); meta.add_text('private', 'synthetic reference')
    Image.new('RGB', (8, 8)).save(source, format='PNG', pnginfo=meta)
    clean = m.private_png(base64.b64encode(source.getvalue()).decode())
    assert b'synthetic reference' not in clean
    assert Image.open(io.BytesIO(clean)).size == (8, 8)
    for value in ['invalid!', base64.b64encode(b'not a photo').decode(), base64.b64encode(b'x'*1048577).decode()]:
        error('bad_photo', lambda: m.private_png(value))


def reviewed(verdict='approved', **changes):
    pending=m.submit('seller-1',FACTS,issued(),1,'challenge-1','123456','submit-01',NOW)
    review=dict(challenge_id='challenge-1',proof_revision=2,watch_revision=1,listing_revision=1,verdict=verdict,
                reviewer_id='reviewer-1',assignment_revision=1,review_revision=1,reason='Synthetic review notes ملاحظات ⌚')
    review.update(changes)
    return pending,dict(FACTS,review=review)


@pytest.mark.parametrize('verdict',['approved','correction','rejected','suspended'])
def test_current_review_status_is_bound_and_never_guessed(verdict):
    pending,facts=reviewed(verdict)
    result=m.current(pending,facts,NOW)
    assert result['state']==verdict
    assert result['review']['reason']==facts['review']['reason']
    if verdict in {'correction','rejected'}:
        assert m.issue('seller-1','listing-1',facts,pending,2,'issue-0002',NOW)['state']=='issued'
    else:
        error('proof_pending',lambda:m.issue('seller-1','listing-1',facts,pending,2,'issue-0002',NOW))
    assert m.current(pending,FACTS,NOW)['state']=='pending'


@pytest.mark.parametrize('changes',[{'reviewer_id':'seller-1'},{'proof_revision':1},{'watch_revision':2},{'assignment_revision':0},{'reason':''},{'verdict':'invented'},{'verdict':[]},{'verdict':{}},{'reviewer_id':1},{'reviewer_id':['reviewer-1']},{'reviewer_id':' '},{'watch_revision':True},{'listing_revision':True}])
def test_stale_denied_or_unreasoned_review_is_unavailable(changes):
    pending,facts=reviewed(**changes)
    error('unavailable',lambda:m.current(pending,facts,NOW))
