import importlib.util
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load('fit_contract_test', 'packages/contracts-service/fit-measurement/v1.py')
model = load('fit_model_test', 'services/service-operations/modules/fit-measurement/model.py')
routes = load('fit_routes_test', 'services/service-operations/modules/fit-measurement/routes.py')
ACTOR = UUID('00000000-0000-4000-8000-000000000001')


def command(**changes):
    body = dict(schema_version='fit-measurement.v1', operation_id='00000000-0000-4000-8000-000000000002',
                subject_id=str(ACTOR), watch_id='00000000-0000-4000-8000-000000000003',
                organization_id='00000000-0000-4000-8000-000000000004', expected_revision=0,
                source_revision=1, circumference='17.5cm', unit='cm', method='tape',
                source='buyer_measured', target='comfortable', final_fit_pass=False)
    return contract.Command.model_validate_json(json.dumps({**body, **changes}))


def proof(body=None, **changes):
    body = body or command()
    return {**{key: str(getattr(body, key)) for key in ('subject_id', 'watch_id', 'organization_id')},
            'actor_id': str(ACTOR), 'allowed': True, 'source_revision': 1, **changes}


@pytest.mark.parametrize('raw,unit,expected', [
    ('17.5cm', 'cm', 175), ('١٧٫٥ سم', 'cm', 175), ('۱۷٫۵ سم', 'cm', 175),
    ('175', 'mm', 175), ('٨٠ مم', 'mm', 80), ('30cm', 'cm', 300),
    ('8.0', 'cm', 80), ('300.0 mm', 'mm', 300),
])
def test_exact(raw, unit, expected):
    assert contract.millimeters(raw, unit) == expected


@pytest.mark.parametrize('raw,unit', [
    ('17,5', 'cm'), ('1,750', 'mm'), ('١٧٬٥', 'cm'), ('17.50', 'cm'),
    ('17٫.5', 'cm'), ('1e2', 'mm'), ('+175', 'mm'), ('175.5', 'mm'),
    ('7.9', 'cm'), ('30.1', 'cm'), ('79', 'mm'), ('301', 'mm'),
    ('17.5 mm', 'cm'), ('175cm', 'mm'), ('NaN', 'cm'), ('∞', 'mm'),
    ('', 'mm'), ('1' * 33, 'cm'),
])
def test_invalid(raw, unit):
    with pytest.raises(contract.MeasurementError):
        contract.millimeters(raw, unit)


@pytest.mark.parametrize('changes', [dict(final_fit_pass=True), dict(final_fit_pass=0),
    dict(source='quality_reviewer'), dict(expected_revision=True), dict(source_revision=0),
    dict(target='passed'), dict(evidence='private'), dict(actor_id=str(ACTOR))])
def test_schema_rejects_inference_or_extra_authority(changes):
    with pytest.raises(ValueError):
        command(**changes)


def test_success_duplicate_lost_response_and_restart_receipt():
    body = command()
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    result = model.resolve(body, ACTOR, proof(), None, None, 175, now)
    assert result['revision'] == 1 and result['final_fit_pass'] is False
    assert result['recorded_at'] == '2026-11-17T00:00:00+00:00'
    retained = json.loads(json.dumps(dict(actor_id=str(ACTOR), organization_id=str(body.organization_id),
                                         request_hash=model.digest(body), result=result)))
    assert model.resolve(body, ACTOR, proof(), retained, {'revision': 9}, 175) == result
    with pytest.raises(model.Rejected, match='operation_conflict'):
        model.resolve(command(target='loose'), ACTOR, proof(), retained, {'revision': 1}, 175)
    with pytest.raises(model.Rejected, match='denied'):
        model.resolve(body, ACTOR, proof(allowed=False), retained, {'revision': 1}, 175)


@pytest.mark.parametrize('key', ['actor_id', 'subject_id', 'watch_id', 'organization_id'])
def test_cross_scope(key):
    with pytest.raises(model.Rejected, match='denied'):
        model.resolve(command(), ACTOR, proof(**{key: 'different'}), None, None, 175)


@pytest.mark.parametrize('expected,current,allowed', [(0, None, True), (0, {'revision': 1}, False),
    (1, {'revision': 1}, True), (2, {'revision': 1}, False)])
def test_revision_boundaries(expected, current, allowed):
    body = command(expected_revision=expected)
    if allowed:
        assert model.resolve(body, ACTOR, proof(), None, current, 175)['revision'] == expected + 1
    else:
        with pytest.raises(model.Rejected, match='stale_revision'):
            model.resolve(body, ACTOR, proof(), None, current, 175)


@pytest.mark.parametrize('revision', [0, 2])
def test_source_boundaries(revision):
    with pytest.raises(model.Rejected):
        model.resolve(command(), ACTOR, proof(source_revision=revision), None, None, 175)


class Tx:
    def __init__(self):
        self.statements = []
        self.saved = None
        self.current = None
        self.commits = 0
        self.rollbacks = 0
        self.fail_outbox = False

    async def __aenter__(self):
        self.before = (self.saved, self.current)
        return self

    async def __aexit__(self, kind, value, traceback):
        if kind:
            self.saved, self.current = self.before
            self.rollbacks += 1
        else:
            self.commits += 1

    def transaction(self):
        return self

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        if sql.startswith('INSERT INTO l25_fit_outbox') and self.fail_outbox:
            raise ConnectionError('unavailable')
        if sql.startswith('INSERT INTO l25_fit_operations'):
            self.saved = dict(actor_id=args[1], organization_id=args[2], request_hash=args[3], result=args[4])
        if sql.startswith('INSERT INTO l25_fit_records'):
            self.current = dict(revision=args[3], result=args[4])

    async def fetchrow(self, sql, *args):
        return self.saved if 'l25_fit_operations' in sql else self.current


class Pool:
    def __init__(self, tx):
        self.tx = tx

    def acquire(self, **kwargs):
        class Acquisition:
            async def __aenter__(inner):
                return self.tx

            async def __aexit__(inner, *args):
                pass
        return Acquisition()


def application(tx, provider):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes.router)
    app.state.pool = Pool(tx)
    if provider:
        app.state.fit_measurement_authority = provider
    return app


@pytest.mark.asyncio
async def test_route_atomic_save_duplicate_and_revocation():
    from httpx import ASGITransport, AsyncClient
    tx, allowed = Tx(), True

    async def provider(*args):
        return ACTOR, proof(allowed=allowed)

    async with AsyncClient(transport=ASGITransport(app=application(tx, provider)), base_url='http://test') as client:
        body = json.loads(command().model_dump_json())
        first = await client.post('/v1/fit-measurement/records', json=body)
        assert first.status_code == 200
        assert first.json()['circumference_mm'] == 175
        again = await client.post('/v1/fit-measurement/records', json=body)
        assert again.json() == first.json()
        assert len([s for s, _ in tx.statements if s.startswith('INSERT INTO l25_fit_outbox')]) == 1
        allowed = False
        assert (await client.post('/v1/fit-measurement/records', json=body)).status_code == 403
        assert tx.commits == 2 and tx.rollbacks == 1


@pytest.mark.asyncio
async def test_missing_provider_timeout_and_body_bound():
    import asyncio
    from httpx import ASGITransport, AsyncClient
    tx = Tx()

    async def slow(*args):
        raise TimeoutError()

    for provider in (None, slow):
        async with AsyncClient(transport=ASGITransport(app=application(tx, provider)), base_url='http://test') as client:
            response = await asyncio.wait_for(client.post('/v1/fit-measurement/records', content=command().model_dump_json()), 2)
            assert response.status_code == 503
            assert (await client.post('/v1/fit-measurement/records', content='x' * 2049)).status_code == 413
    assert tx.saved is None


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_record_and_receipt():
    from httpx import ASGITransport, AsyncClient
    tx = Tx()
    tx.fail_outbox = True

    async def provider(*args):
        return ACTOR, proof()

    async with AsyncClient(transport=ASGITransport(app=application(tx, provider), raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.post('/v1/fit-measurement/records', content=command().model_dump_json())
        assert response.status_code >= 500
    assert tx.current is None and tx.saved is None and tx.rollbacks == 1


@pytest.mark.asyncio
async def test_private_context_denial_and_restart_read():
    from httpx import ASGITransport, AsyncClient
    tx, allowed = Tx(), True

    async def provider(*args):
        return ACTOR, proof(allowed=allowed)

    body = command()
    query = {key: str(getattr(body, key)) for key in ('subject_id', 'watch_id', 'organization_id')}
    async with AsyncClient(transport=ASGITransport(app=application(tx, provider)), base_url='http://test') as client:
        assert (await client.get('/v1/fit-measurement/context', params=query)).json()['record'] is None
        saved = (await client.post('/v1/fit-measurement/records', content=body.model_dump_json())).json()
    async with AsyncClient(transport=ASGITransport(app=application(tx, provider)), base_url='http://test') as client:
        assert (await client.get('/v1/fit-measurement/context', params=query)).json()['record'] == saved
        allowed = False
        response = await client.get('/v1/fit-measurement/context', params=query)
        assert response.status_code == 403 and 'circumference' not in response.text


def test_published_schema_and_fixtures():
    schema = json.loads((ROOT / 'packages/contracts-service/fit-measurement/schema.v1.json').read_text())
    assert schema == contract.Command.model_json_schema()
    fixture = json.loads((ROOT / 'packages/contracts-service/fit-measurement/fixtures.json').read_text())
    body = contract.Command.model_validate_json(json.dumps(fixture['command']))
    assert fixture['synthetic'] is True
    assert contract.millimeters(body.circumference, body.unit) == fixture['record']['circumference_mm']


def test_assigned_business_read_does_not_grant_buyer_write():
    body = command()
    staff = UUID('00000000-0000-4000-8000-000000000005')
    current = proof(actor_id=str(staff))
    model.require_authority(current, staff, body, buyer_only=False)
    with pytest.raises(model.Rejected, match='denied'):
        model.resolve(body, staff, current, None, None, 175)
