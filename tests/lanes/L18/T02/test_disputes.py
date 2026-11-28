import asyncio
import importlib.util
import json
import sys
import types
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / 'services/trust/modules/disputes'
package = types.ModuleType('l18_disputes')
package.__path__ = [str(PACKAGE)]
sys.modules['l18_disputes'] = package
spec = importlib.util.spec_from_file_location('l18_disputes.service', PACKAGE / 'service.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Service, Source, Rejected, Command = module.Service, module.Source, module.Rejected, module.Command
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


class Provider:
    def __init__(self):
        self.source = Source('order_1', 'watch_1', 'buyer', 'seller', None, 1, 1, 'reviewer',
                             'private_watch', NOW - timedelta(hours=1), 'receipt_1', 'quote_1',
                             1, 1, 1, 500000, 15000, 25000, 'seller_recipient', True, 'operator_1')
        self.state = 'confirmed'
        self.calls = []
        self.receipts = {}
        self.allowed = True
        self.evidence_valid = True

    async def current(self, credential, subject, organization):
        if not self.allowed:
            raise Rejected('denied')
        return credential, self.source

    async def evidence(self, credential, subject, evidence):
        return self.evidence_valid

    async def apply(self, binding):
        self.calls.append(binding)
        if self.state == 'timeout':
            raise TimeoutError()
        if self.state == 'malformed':
            return None
        if self.state == 'mismatch':
            return {'state': 'confirmed', 'binding_hash': 'wrong'}
        # Represents the producer's stable inbox receipt, never a money journal.
        return self.receipts.setdefault(binding['financial_operation_id'],
            {'state': self.state, 'binding_hash': binding['binding_hash']})


def run(awaitable):
    return asyncio.run(awaitable)


def command(kind='open', operation='operation_1', revision=0, **kw):
    return Command(operation_id=operation, subject_id='order_1', expected_revision=revision,
                   source_revision=1, assignment_revision=1, kind=kind, reason='Recorded reason', **kw)


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    return Service(tmp_path / 'cases.db', provider, lambda: NOW), provider


def test_confirm_hold_duplicate_private_detail_and_restart(setup):
    service, provider = setup
    result = run(service.command('buyer', command()))
    assert result['state'] == 'open'
    assert 'reason' not in result and 'evidence' not in result
    assert run(service.command('buyer', command(operation='other_operation'))) == result
    restarted = Service(service.database, provider, lambda: NOW)
    assert run(restarted.read('buyer', 'order_1', None, 'operation_1')) == result
    assert len(provider.receipts) == 1
    assert run(restarted.context('seller', 'order_1', None))['case']['reason'] == 'Recorded reason'


@pytest.mark.parametrize('kind,hours', [('private_watch', 72), ('business_watch', 168), ('job', 168)])
@pytest.mark.parametrize('offset,accepted', [(-1, True), (0, False), (1, False)])
def test_deadline_before_equal_after(setup, kind, hours, offset, accepted):
    service, provider = setup
    provider.source = replace(provider.source, kind=kind, received_at=NOW-timedelta(hours=hours)+timedelta(seconds=-offset))
    if accepted:
        assert run(service.command('buyer', command()))['state'] == 'open'
    else:
        with pytest.raises(Rejected, match='late') as error:
            run(service.command('buyer', command()))
        assert error.value.closing_at
        assert not provider.calls


@pytest.mark.parametrize('state', ['timeout', 'pending', 'malformed', 'mismatch'])
def test_unknown_hold_restart_same_reference(setup, state):
    service, provider = setup
    provider.state = state
    assert run(service.command('buyer', command()))['state'] == 'hold_pending'
    assert run(service.context('buyer', 'order_1', None))['case']['state'] == 'hold_pending'
    provider.state = 'confirmed'
    provider.receipts.clear()
    restarted = Service(service.database, provider, lambda: NOW)
    assert run(restarted.read('buyer', 'order_1', None, 'operation_1'))['state'] == 'open'
    assert {x['financial_operation_id'] for x in provider.calls} == {'dispute_operation_1'}


@pytest.mark.parametrize('kind', ['private_watch', 'business_watch', 'job'])
def test_response_independent_principal_only_refund(setup, kind):
    service, provider = setup
    provider.source = replace(provider.source, kind=kind)
    opened = run(service.command('buyer', command()))
    response = run(service.command('seller', command('respond', 'response_1', opened['revision'])))
    with pytest.raises(Rejected, match='denied'):
        run(service.command('buyer', command('refund', 'refund_denied', response['revision'], amount_minor=500000)))
    refunded = run(service.command('reviewer', command('refund', 'refund_1', response['revision'], amount_minor=500000)))
    assert refunded['state'] == 'refunded'
    binding = provider.calls[-1]
    assert binding['amount_minor'] == 500000
    assert binding['buyer_fee_minor'] == 15000 and binding['business_fee_minor'] == 25000
    assert binding['recipient_id'] == 'seller_recipient'
    assert binding['hold_operation_id'] == 'dispute_operation_1'
    with pytest.raises(Rejected, match='pending'):
        run(service.command('reviewer', command('refund', 'refund_again', refunded['revision'], amount_minor=1)))


def test_current_access_and_revision(setup):
    service, provider = setup
    with pytest.raises(Rejected, match='denied'):
        run(service.command('stranger', command()))
    with pytest.raises(Rejected, match='denied'):
        run(service.command('buyer', command(organization_id='other')))
    with pytest.raises(Rejected, match='stale'):
        run(service.command('buyer', command(revision=2)))
    provider.source = replace(provider.source, revision=2)
    with pytest.raises(Rejected, match='stale'):
        run(service.command('buyer', command()))
    provider.source = replace(provider.source, revision=1)
    run(service.command('buyer', command()))
    provider.allowed = False
    with pytest.raises(Rejected, match='denied'):
        run(service.command('buyer', command()))
    with pytest.raises(Rejected, match='denied'):
        run(service.context('buyer', 'order_1', None))


def test_reassignment_and_self_review(setup):
    service, provider = setup
    opened = run(service.command('buyer', command()))
    provider.source = replace(provider.source, reviewer_id='replacement', assignment_revision=2)
    with pytest.raises(Rejected, match='denied'):
        run(service.context('reviewer', 'order_1', None))
    with pytest.raises(Rejected, match='stale'):
        run(service.command('replacement', command('release', 'release_1', opened['revision'])))
    provider.source = replace(provider.source, reviewer_id='seller', assignment_revision=1)
    with pytest.raises(Rejected, match='denied'):
        run(service.command('seller', command('release', 'release_1', opened['revision'])))


def test_resolution_unknown_and_denied_remain_held(setup):
    service, provider = setup
    opened = run(service.command('buyer', command()))
    provider.state = 'timeout'
    result = run(service.command('reviewer', command('release', 'release_1', opened['revision'])))
    assert result['state'] == 'release_pending'
    with pytest.raises(Rejected, match='pending'):
        run(service.command('reviewer', command('refund', 'refund_1', result['revision'], amount_minor=500000)))
    provider.state = 'denied'
    result = run(service.read('reviewer', 'order_1', None, 'release_1'))
    assert result['state'] == 'open' and result['pending_reason'] == 'orders_denied'


def test_conflicting_retry_denied_hold_and_prerequisites(setup):
    service, provider = setup
    provider.state = 'denied'
    assert run(service.command('buyer', command()))['state'] == 'denied'
    with pytest.raises(Rejected, match='conflict'):
        run(service.command('buyer', command(amount_minor=1)))


@pytest.mark.parametrize('changes', [{'ready': False}, {'received_at': NOW+timedelta(seconds=1)}])
def test_no_invented_receipt_or_readiness(setup, changes):
    service, provider = setup
    provider.source = replace(provider.source, **changes)
    with pytest.raises(Rejected, match='prerequisites'):
        run(service.command('buyer', command()))


def test_evidence_and_minor_unit_bounds(setup):
    service, provider = setup
    evidence = {'reference': 'private_ref', 'sha256': 'a'*64, 'size': 20, 'media_type': 'image/png'}
    provider.evidence_valid = False
    with pytest.raises(Rejected, match='evidence'):
        run(service.command('buyer', command(evidence=[evidence])))
    for amount in [True, 0.5, -1, 9007199254740992]:
        with pytest.raises(ValueError):
            command(amount_minor=amount)
    for reason in ['', '   ']:
        with pytest.raises(ValueError):
            Command(**{**command().model_dump(), 'reason': reason})


def test_deterministic_fixture_contract():
    data = json.loads((ROOT/'packages/contracts-trust/disputes/fixtures.json').read_text())
    assert data['synthetic'] and len(data['cases']) == 6


def test_business_response_current_grant_and_operator(setup):
    service, provider = setup
    provider.source = replace(provider.source, organization_id='business_1', business_responders=('colleague',))
    opened = run(service.command('buyer', command(organization_id='business_1')))
    assert opened['next_actor'] == 'operator_1' and opened['next_action'] == 'independent_review'
    response = run(service.command('colleague', command('respond', 'response_1', opened['revision'], organization_id='business_1')))
    assert response['state'] == 'responded'
    provider.source = replace(provider.source, business_responders=())
    with pytest.raises(Rejected, match='denied'):
        run(service.context('colleague', 'order_1', 'business_1'))


def test_complete_fixture_envelopes():
    data = json.loads((ROOT/'packages/contracts-trust/disputes/fixtures.json').read_text())
    for case in data['cases']:
        Command.model_validate(case['request'])
        if 'result' in case:
            sys.modules['l18_disputes.contracts']._contract.Result.model_validate(case['result'])
        else:
            assert case['error'] == {'code': 'stale', 'status': 409}


def test_routes_protected_files_and_reassignment(setup):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from l18_disputes.routes import router_for
    service, provider = setup
    content = b'%PDF-1.7 synthetic evidence'
    checksum = module.hashlib.sha256(content).hexdigest()
    item = {'reference':'private_ref','sha256':checksum,'size':len(content),'media_type':'application/pdf'}
    async def stage(credential, subject, organization, operation, data, media, sha):
        assert data == content and sha == checksum
        return item
    async def download(credential, subject, organization, reference):
        return content
    provider.stage, provider.download = stage, download
    actor = ['buyer']
    app = FastAPI()
    async def credential():
        return actor[0]
    app.include_router(router_for(service, credential))
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/v1/disputes/evidence/order_1', content=content,
                headers={'Content-Type':'application/pdf','Idempotency-Key':'operation_1','X-Content-SHA256':checksum})
            assert response.status_code == 200 and response.json() == item
            assert response.headers['cache-control'] == 'no-store'
            assert (await client.get('/v1/disputes/evidence/order_1/private_ref')).status_code == 403
            body = command(evidence=[item]).model_dump(mode='json')
            assert (await client.post('/v1/disputes/commands', json=body)).json()['state'] == 'open'
            actor[0] = 'reviewer'
            assert (await client.get('/v1/disputes/evidence/order_1/private_ref')).status_code == 200
            provider.source = replace(provider.source, reviewer_id='replacement')
            assert (await client.get('/v1/disputes/evidence/order_1/private_ref')).status_code == 403
            actor[0] = 'buyer'
            assert (await client.post('/v1/disputes/commands', content=b' '*40001)).status_code == 413
            assert (await client.post('/v1/disputes/commands', json={**body,'amount_minor':True})).status_code == 422
            provider.allowed = False
            response = await client.get('/v1/disputes/order_1')
            assert response.status_code == 403 and response.json()['error']['code'] == 'denied'

    run(exercise())


@pytest.mark.parametrize('kind', ['refund', 'release'])
def test_decision_evidence_survives_restart_and_authorized_download(setup, kind):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from l18_disputes.routes import router_for
    service, provider = setup
    content = b'%PDF-1.7 decision evidence'
    item = {'reference': 'decision_ref', 'sha256': module.hashlib.sha256(content).hexdigest(),
            'size': len(content), 'media_type': 'application/pdf'}
    opened = run(service.command('buyer', command()))
    result = run(service.command('reviewer', command(kind, 'decision_1', opened['revision'],
                 evidence=[item], amount_minor=500000 if kind == 'refund' else 0)))
    assert 'decision' not in result
    restarted = Service(service.database, provider, lambda: NOW)
    assert run(restarted.context('buyer', 'order_1', None))['case']['decision']['evidence'] == [item]
    async def download(*args):
        return content
    provider.download = download
    actor = ['buyer']
    async def credential():
        return actor[0]
    app = FastAPI()
    app.include_router(router_for(restarted, credential))
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/v1/disputes/evidence/order_1/decision_ref')
            assert response.status_code == 200
            import base64
            assert base64.b64decode(response.json()['content_base64']) == content
            actor[0] = 'stranger'
            assert (await client.get('/v1/disputes/evidence/order_1/decision_ref')).status_code == 403
    run(exercise())


@pytest.mark.parametrize('kind', ['refund', 'release'])
def test_replacement_reconciles_original_decision_after_restart(setup, kind):
    service, provider = setup
    opened = run(service.command('buyer', command()))
    provider.state = 'timeout'
    pending = run(service.command('reviewer', command(kind, 'decision_1', opened['revision'],
                  amount_minor=500000 if kind == 'refund' else 0)))
    binding = provider.calls[-1].copy()
    provider.source = replace(provider.source, reviewer_id='replacement', assignment_revision=2)
    restarted = Service(service.database, provider, lambda: NOW)
    for actor in ('reviewer', 'stranger', 'operator_1'):
        with pytest.raises(Rejected, match='denied'):
            run(restarted.read(actor, 'order_1', None, 'decision_1'))
    with pytest.raises(Rejected, match='denied'):
        run(restarted.read('replacement', 'order_1', 'other', 'decision_1'))
    assert run(restarted.read('replacement', 'order_1', None, 'decision_1')) == pending
    provider.state = 'confirmed'
    completed = run(restarted.read('replacement', 'order_1', None, 'decision_1'))
    assert completed['state'] == ('refunded' if kind == 'refund' else 'released')
    assert completed['financial_operation_id'] == pending['financial_operation_id']
    assert provider.calls[-1] == binding
    assert len(provider.receipts) == 2
    assert run(restarted.read('replacement', 'order_1', None, 'decision_1')) == completed


@pytest.mark.parametrize('change,code', [
    ('revoked', 'denied'), ('membership', 'denied'), ('source', 'stale'), ('assignment', 'stale')])
def test_response_revalidates_after_evidence_before_persistence(setup, change, code):
    service, provider = setup
    provider.source = replace(provider.source, business_responders=('colleague',))
    opened = run(service.command('buyer', command()))
    before = run(service.context('buyer', 'order_1', None))['case']
    async def verify(*args):
        if change == 'revoked':
            provider.allowed = False
        elif change == 'membership':
            provider.source = replace(provider.source, business_responders=())
        elif change == 'source':
            provider.source = replace(provider.source, revision=2)
        else:
            provider.source = replace(provider.source, assignment_revision=2)
        return True
    provider.evidence = verify
    evidence = {'reference': 'private_ref', 'sha256': 'a'*64, 'size': 20, 'media_type': 'image/png'}
    with pytest.raises(Rejected, match=code):
        run(service.command('colleague', command('respond', 'response_1', opened['revision'], evidence=[evidence])))
    with service.connect() as db:
        assert json.loads(db.execute('SELECT body FROM l18_dispute_cases').fetchone()['body']) == before
        assert db.execute('SELECT COUNT(*) FROM l18_dispute_operations WHERE operation=?', ('response_1',)).fetchone()[0] == 0
    assert len(provider.calls) == 1


def test_sanitized_image_reference_uses_stored_integrity(setup):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from l18_disputes.routes import router_for
    import base64
    service, provider = setup
    uploaded = b'\x89PNG\r\n\x1a\nsynthetic image with private metadata'
    stored = b'\x89PNG\r\n\x1a\nsynthetic sanitized image'
    upload_hash = module.hashlib.sha256(uploaded).hexdigest()
    item = {'reference': 'sanitized_ref', 'sha256': module.hashlib.sha256(stored).hexdigest(),
            'size': len(stored), 'media_type': 'image/png'}
    calls = []
    async def stage(credential, subject, organization, operation, data, media, checksum):
        calls.append(operation)
        assert data == uploaded and checksum == upload_hash
        return item
    async def download(*args):
        return stored
    provider.stage, provider.download = stage, download
    async def credential():
        return 'buyer'
    app = FastAPI()
    app.include_router(router_for(service, credential))
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            headers = {'Content-Type': 'image/png', 'Idempotency-Key': 'operation_1',
                       'X-Content-SHA256': upload_hash}
            for _ in range(2):
                response = await client.post('/v1/disputes/evidence/order_1', content=uploaded, headers=headers)
                assert response.status_code == 200 and response.json() == item
            response = await client.post('/v1/disputes/evidence/order_1', content=stored, headers=headers)
            assert response.status_code == 422 and len(calls) == 2
            response = await client.post('/v1/disputes/commands', json=command(evidence=[item]).model_dump(mode='json'))
            assert response.json()['state'] == 'open'
            response = await client.get('/v1/disputes/evidence/order_1/sanitized_ref')
            assert response.status_code == 200
            assert base64.b64decode(response.json()['content_base64']) == stored
            assert response.headers['cache-control'] == 'no-store'
            async def corrupted(*args):
                return stored[:-1] + b'!'
            provider.download = corrupted
            assert (await client.get('/v1/disputes/evidence/order_1/sanitized_ref')).status_code == 503
    run(exercise())
