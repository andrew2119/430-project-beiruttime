"""Pure contracts, authorization boundaries and durable-receipt adapter checks."""
import ast
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
import json
import unittest
from types import SimpleNamespace

import pytest
import sys
from uuid import UUID
from pydantic import ValidationError
from service_app.modules import discover

from bt_contracts.service.maintenance import v1 as contract
from bt_contracts.service.case_lines import v1 as lines
from bt_contracts.service.intake import current

MODULES = Path('/app/modules')
if not MODULES.is_dir():
    MODULES = Path(__file__).resolve().parents[4] / 'services/service-operations/modules'
inventory = {module.id: module for module in discover(MODULES)}
submit = inventory['L17.maintenance-requests'].load('commands.py:submit')
authorize_record = inventory['L09.intake'].load('access.py:record_access')
commands = sys.modules[submit.__module__]
access = sys.modules[authorize_record.__module__]
authority = import_module('.authority', access.__package__)


def uid(n):
    return UUID(int=n)


def request(**changes):
    body = dict(operation_id=uid(1), subject_id=uid(2), actor_id=uid(2), organization_id=uid(3),
        watch_id=uid(4), expected_revision=0, watch_revision=2, capability_revision=3, policy_revision=1,
        brand_id=uid(5), intervention='limited_maintenance', reported_symptoms='توقف ABC ⌚',
        known_modifications='', photo_refs=[], limited_assessment_permission=True)
    return contract.Request(**(body | changes))


class Provider:
    def __init__(self, **changes):
        self.facts = dict(identity_current=True, watch_owned=True, business_active=True,
            assessment_supported=True, commitment_available=True, private_refs_current=True,
            watch_revision=2, capability_revision=3, policy_revision=1) | changes

    async def current(self, body):
        return {key:getattr(body,key) for key in ('actor_id','subject_id','watch_id','organization_id','brand_id','intervention','operation_id')} | self.facts


class Store:
    def __init__(self):
        self.operations = {}
        self.writes = []

    @asynccontextmanager
    async def transaction(self, key):
        yield self

    async def fetchrow(self, sql, *args):
        return self.operations.get(args[0])

    async def execute(self, sql, *args):
        self.writes.append((sql, args))
        if 'INSERT INTO maintenance_request_operations' in sql:
            self.operations[args[0]] = {'request_hash': args[3], 'result': args[4]}


@pytest.mark.asyncio
async def test_admission_checks_live_capability_revision_for_new_requests(monkeypatch):
    provider_type = inventory['L17.maintenance-requests'].load('provider.py:Provider')
    module = sys.modules[provider_type.__module__]
    body = request()
    store = Store()
    live_revision = body.capability_revision + 1

    async def admission(_, name, *scope):
        assert name == 'maintenance_admission'
        assert scope == (body.actor_id, body.watch_id, body.organization_id,
                         body.operation_id, body.intervention)
        facts = await Provider().current(body)
        del facts['private_refs_current']
        return facts

    async def official(_, organization, capability):
        assert (organization, capability) == (body.organization_id, 'servicing')
        return {'revision': live_revision}

    class PhotoReferences:
        async def fetch(self, *args):
            return []

    @asynccontextmanager
    async def acquire():
        yield PhotoReferences()

    monkeypatch.setattr(module, 'prerequisite', admission)
    monkeypatch.setattr(module, 'official_business', official)
    provider = provider_type(SimpleNamespace(app=SimpleNamespace(
        state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire)))))

    async def submit_request():
        return await submit(body, actor_id=body.actor_id, provider=provider,
                            transaction=store.transaction)

    with pytest.raises(commands.Rejected, match='stale'):
        await submit_request()
    assert store.writes == []
    live_revision = body.capability_revision
    receipt = await submit_request()
    live_revision += 1
    assert await submit_request() == receipt
    assert len(store.writes) == 3


class Admission(unittest.IsolatedAsyncioTestCase):
    async def test_submission_before_payment_is_not_booking_receipt_or_work(self):
        store = Store()
        body = request()
        result = await commands.submit(body, actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        self.assertEqual(result['state'], 'submitted')
        self.assertNotIn('reported_symptoms', result)
        self.assertNotIn('photo_refs', result)
        self.assertEqual(len(store.writes), 3)
        self.assertEqual(contract.Result(**result).revision, 1)
        outbox = store.writes[1][1]
        self.assertNotIn(body.reported_symptoms, str(outbox))

    async def test_lost_response_restart_replays_one_receipt(self):
        store = Store()
        body = request()
        original = await commands.submit(body, actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        restarted = Store()
        restarted.operations = json.loads(json.dumps({str(k):v for k,v in store.operations.items()}))
        restarted.operations = {UUID(k):v for k,v in restarted.operations.items()}
        replay = await commands.submit(body, actor_id=uid(2), provider=Provider(), transaction=restarted.transaction)
        self.assertEqual(original, replay)
        self.assertEqual(restarted.writes, [])

    async def test_cross_actor_stale_denied_and_revoked_replay(self):
        store = Store()
        for actor, provider, expected in [(uid(8), Provider(), 'denied'),
            (uid(2), Provider(assessment_supported=False), 'denied'),
            (uid(2), Provider(capability_revision=4), 'stale'),
            (uid(2), Provider(watch_revision=3), 'stale'),
            (uid(2), Provider(private_refs_current=False), 'denied')]:
            with self.subTest(expected=expected), self.assertRaisesRegex(commands.Rejected, expected):
                await commands.submit(request(), actor_id=actor, provider=provider, transaction=store.transaction)
        self.assertEqual(store.writes, [])
        await commands.submit(request(), actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        with self.assertRaisesRegex(commands.Rejected, 'denied'):
            await commands.submit(request(), actor_id=uid(2), provider=Provider(identity_current=False), transaction=store.transaction)

    async def test_committed_retry_survives_changed_source_revisions(self):
        store = Store()
        original = await commands.submit(request(), actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        for changes in ({'capability_revision':4}, {'watch_revision':3}, {'policy_revision':2}):
            replay = await commands.submit(request(), actor_id=uid(2), provider=Provider(**changes), transaction=store.transaction)
            self.assertEqual(replay, original)
        self.assertEqual(len(store.writes), 3)

    async def test_conflicting_duplicate_is_rejected(self):
        store = Store()
        await commands.submit(request(), actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        with self.assertRaisesRegex(commands.Rejected, 'operation_conflict'):
            await commands.submit(request(known_modifications='Changed'), actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        self.assertEqual(len(store.writes), 3)

    async def test_missing_and_timeout_facts_stay_pending(self):
        class Missing:
            async def current(self, body):
                return None
        class Timeout:
            async def current(self, body):
                raise TimeoutError
        for provider in (Missing(), Timeout()):
            store = Store()
            with self.assertRaisesRegex(commands.Rejected, 'pending'):
                await commands.submit(request(), actor_id=uid(2), provider=provider, transaction=store.transaction)
            self.assertEqual(store.writes, [])


class PrivateAccess(unittest.IsolatedAsyncioTestCase):
    async def test_current_assigned_record_access_and_revocation(self):
        from fastapi import HTTPException
        from types import SimpleNamespace as N
        p = N(actor=N(subject_id=uid(2)))
        value = dict(actor_id=uid(2),organization_id=uid(3),order_id=uid(7),
            permission='read',assignment_revision=1,allowed=True)
        class Provider:
            async def record_access(self, *args):
                return value
        request = N(app=N(state=N(intake_current_authority=Provider())))
        self.assertTrue((await access.record_access(p,request,uid(3),uid(7),'read')).allowed)
        for change in ({'allowed':False},{'actor_id':uid(8)},{'organization_id':uid(8)},{'order_id':uid(8)}):
            old=value.copy()
            value.update(change)
            with self.assertRaises(HTTPException) as error:
                await access.record_access(p,request,uid(3),uid(7),'read')
            self.assertEqual(error.exception.status_code,403)
            value.clear()
            value.update(old)
        request.app.state.intake_current_authority=None
        with self.assertRaises(HTTPException) as error:
            await access.record_access(p,request,uid(3),uid(7),'read')
        self.assertEqual(error.exception.status_code,503)


def route_function(name, namespace):
    tree=ast.parse((MODULES / 'intake/routes.py').read_text())
    function=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name==name)
    exec(compile(ast.Module(body=[function],type_ignores=[]),'intake_routes','exec'),namespace)
    return namespace[name]

class CurrentOpening(unittest.IsolatedAsyncioTestCase):
    async def test_historical_retry_withholds_opening_and_preserves_receipt(self):
        from types import SimpleNamespace as N
        from bt_contracts_core.errors import PublicError
        original = dict(id=str(uid(9)),revision=2,state='received',diagnosis_allowed=True)
        stored = json.dumps(original)
        class Tx:
            async def fetchrow(self,*args):
                return dict(request_hash='digest',result=stored)
        @asynccontextmanager
        async def transaction(*args,**kwargs):
            yield Tx()
        async def organization(*args):return uid(3)
        async def record_access(*args):return None
        save=route_function('save',dict(organization=organization,record_access=record_access,
            operation=lambda *args:('original-reference','digest'),PublicError=PublicError,
            unit_of_work=transaction,json=json))
        for provider in (None, N(permission=False)):
            result=await save(N(currency='USD',order_id=uid(7)),
                N(app=N(state=N(pool=None,intake_current_authority=provider))),
                N(actor=N(subject_id=uid(2))))
            self.assertEqual(result,original | {'diagnosis_allowed':False})
            self.assertEqual(json.loads(stored),original)

    async def test_customer_grant_and_accepted_fee_are_authoritative(self):
        facts=dict(actor_id=uid(2),organization_id=uid(3),order_id=uid(7),receipt_id=uid(8),
            receipt_revision=2,watch_id=uid(9),watch_revision=1,incident_revision=0,
            received_at=datetime.now(timezone.utc)-timedelta(seconds=1),current=True,
            assigned=True,permission=True,customer_opening_permission=True,
            accepted_assessment_fee=True,customer_no_polish_acknowledged=True,
            consent_revision=1,accepted_terms_revision=1,quote_id=uid(10),quote_revision=1,
            accepted_fee_minor=5000,currency='USD')
        private = dict(currency='USD', fee_minor=5000, diagnostic_opening_permission=True,
                       fee_acknowledged=True, no_polish_acknowledged=True)
        opening = inventory['L09.intake'].load('routes.py:current_opening')
        self.assertTrue(opening(current.OpeningAuthority.model_validate(facts), uid(3), private))
        for field in ('customer_opening_permission', 'accepted_assessment_fee',
                      'customer_no_polish_acknowledged', 'assigned', 'current'):
            denied = current.OpeningAuthority.model_validate({**facts, field: False})
            self.assertFalse(opening(denied, uid(3), private))
        self.assertFalse(opening(current.OpeningAuthority.model_validate(facts), uid(3),
                                 private | {'fee_minor': 0}))

    async def test_direct_legacy_update_cannot_relabel_money(self):
        import re
        from types import SimpleNamespace as N
        from bt_contracts_core.errors import PublicError
        from fastapi import HTTPException
        class Tx:
            async def fetchrow(self,sql,*args):
                if 'technical_intake_operations' in sql:
                    return None
                return dict(private_record=json.dumps({'currency':'LBP','fee_minor':5000}),revision=1)
        @asynccontextmanager
        async def transaction(*args,**kwargs):
            yield Tx()
        async def organization(*args):return uid(3)
        async def record_access(*args):return None
        save=route_function('save',dict(organization=organization,record_access=record_access,
            operation=lambda *args:('operation-1','digest'),re=re,PublicError=PublicError,
            unit_of_work=transaction,json=json,HTTPException=HTTPException))
        with self.assertRaises(PublicError) as error:
            await save(N(currency='USD',order_id=uid(7)),N(headers={'If-Match':'1'},app=N(state=N(pool=None))),N(actor=N(subject_id=uid(2))),uid(9))
        self.assertEqual(error.exception.code,'currency_reissue_required')


class Boundaries(unittest.TestCase):
    def test_published_schemas_and_fixtures_match_models(self):
        for module,names in [(contract,['Request','Result','Context','Photo','RequestAuthority']),
                (lines,['CaseLine','Scope','ScopeReceipt']),
                (current,['OpeningAuthority','RecordAccess','RecordListAccess'])]:
            for name in names:
                schema=json.loads((Path(module.__file__).with_name(name.lower()+'.schema.v1.json')).read_text())
                self.assertEqual(schema,getattr(module,name).model_json_schema())
        for module,model in [(contract,contract.Result),(lines,lines.ScopeReceipt)]:
            fixtures=json.loads((Path(module.__file__).with_name('fixtures.json')).read_text())
            self.assertEqual(set(fixtures),{'success','denied','stale','lost_response'})
            for fixture in fixtures.values():
                model.model_validate(fixture)

    def test_scope_requires_every_mandatory_line_and_integer_usd(self):
        line = dict(line_id=uid(10),kind='maintenance.assessment',description='Assessment',
            required=True,amount_minor=5000,currency='USD',assessment_id=uid(11),assessment_revision=1)
        scope = lines.Scope(request_id=uid(1),request_revision=1,revision=1,lines=[line],accepted_line_ids=[])
        with self.assertRaises(ValueError):
            scope.accepted_total()
        scope.accepted_line_ids=[uid(10)]
        self.assertEqual(scope.accepted_total(),5000)
        for amount in (-1, 0.5, True, 9_000_000_000_001):
            with self.assertRaises(ValidationError):
                lines.CaseLine(**(line | {'amount_minor':amount}))
        with self.assertRaises(ValidationError):
            request(photo_refs=[uid(i) for i in range(11)])

    def test_diagnostic_receipt_before_equal_after_and_revocation(self):
        now = datetime(2026,11,16,tzinfo=timezone.utc)
        receipt = dict(watch_id=uid(1),watch_revision=2,organization_id=uid(3),
            incident_revision=1,current=True,received_at=now)
        args = dict(receipt=receipt,watch_id=uid(1),watch_revision=2,organization_id=uid(3),
            incident_revision=1,now=now,assigned=True,permission=True,opening_permission=True,
            fee_acknowledged=True,no_polish_acknowledged=True)
        for delta, expected in [(-1,True),(0,True),(1,False)]:
            self.assertEqual(authority.diagnostic_opening_allowed(**(args | {'receipt':receipt | {'received_at':now+timedelta(seconds=delta)}})),expected)
        for field in ('assigned','permission','opening_permission'):
            self.assertFalse(authority.diagnostic_opening_allowed(**(args | {field:False})))
        self.assertFalse(authority.diagnostic_opening_allowed(**(args | {'watch_revision':3})))
        self.assertFalse(authority.diagnostic_opening_allowed(**(args | {'incident_revision':2})))

    def test_execution_requires_exact_held_payment(self):
        args = dict(accepted_scope_revision=2,current_scope_revision=2,custody_current=True,
            buyer_id=uid(1),order_id=uid(2),watch_id=uid(3),quote_id=uid(4),quote_revision=1,total_minor=500000)
        payment = {k:args[k] for k in ('buyer_id','order_id','watch_id','quote_id','quote_revision','total_minor')}
        payment.update(currency='USD',state='paid_held',order_kind='job')
        self.assertTrue(authority.execution_allowed(**args,payment=payment))
        for revision in (None, 0, -1, True, 2.0, '2'):
            for field in ('accepted_scope_revision', 'current_scope_revision'):
                self.assertFalse(authority.execution_allowed(**(args | {field:revision}), payment=payment))
            self.assertFalse(authority.execution_allowed(**(args | {
                'accepted_scope_revision':revision, 'current_scope_revision':revision}), payment=payment))
        for kind in ('watch_sale', 'purchase', '', None):
            self.assertFalse(authority.execution_allowed(**args,payment=payment | {'order_kind':kind}))
        self.assertFalse(authority.execution_allowed(**args,
            payment={key:value for key,value in payment.items() if key!='order_kind'}))
        for state in ('unpaid','pending','unknown'):
            self.assertFalse(authority.execution_allowed(**args,payment=payment | {'state':state}))
        self.assertFalse(authority.execution_allowed(**(args | {'current_scope_revision':3}),payment=payment))
        self.assertFalse(authority.execution_allowed(**args,payment=payment | {'total_minor':499999}))

if __name__ == '__main__':
    unittest.main()


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [None, 'actor_id', 'organization_id', 'order_id',
                                     'receipt_id', 'received_at', 'assigned', 'current'])
async def test_received_intake_uses_assigned_custody(monkeypatch, invalid):
    from bt_contracts_core.errors import PublicError
    from datetime import datetime, timedelta, timezone

    receive = inventory['L09.intake'].load('routes.py:assigned_opening')
    actor, org, order, receipt_id, watch, quote = map(uid, range(1, 7))
    received_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    audited = SimpleNamespace(id=receipt_id, order_id=order, organization_id=org,
                             revision=2, received_at=received_at)
    facts = dict(actor_id=actor, organization_id=org, order_id=order, receipt_id=receipt_id,
                 receipt_revision=2, watch_id=watch, watch_revision=1, incident_revision=0,
                 received_at=received_at, current=True, assigned=True, permission=False,
                 customer_opening_permission=False, accepted_assessment_fee=False,
                 customer_no_polish_acknowledged=False, consent_revision=1,
                 accepted_terms_revision=1, quote_id=quote, quote_revision=1,
                 accepted_fee_minor=0, currency='USD')
    if invalid in ('assigned', 'current'):
        facts[invalid] = False
    elif invalid == 'received_at':
        facts[invalid] = received_at + timedelta(days=1)
    elif invalid:
        facts[invalid] = uid(99)

    authority = inventory['L09.intake'].load('current_provider.py:CurrentAuthority')

    async def prerequisite(current_request, name, *scope):
        assert current_request is request
        assert (name, scope) == ('intake_opening_authority', (actor, org, order))
        return facts

    monkeypatch.setattr(sys.modules[authority.__module__], 'prerequisite', prerequisite)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    body = SimpleNamespace(order_id=order, custody_receipt_id=receipt_id)
    if invalid:
        with pytest.raises(PublicError) as error:
            await receive(body, actor, org, request, audited)
        assert error.value.status == 409
    else:
        opening = await receive(body, actor, org, request, audited)
        assert opening.receipt_id == audited.id


@pytest.mark.asyncio
@pytest.mark.parametrize(('change', 'verification', 'allowed'), [
    (None, 'current', True),
    ('permission', 'current', False),
    ('other_journey', 'current', True),
    ('missing_link', 'current', False),
    ('missing_signed_request', 'current', False),
    ('other_request', 'current', False),
    ('wrong_fee_quote', 'current', False),
    ('received_at', 'unconfirmed', False),
    ('revision', 'unconfirmed', False),
    ('opening_stale', 'current', False),
    ('opening_unavailable', 'current', False),
    ('custody_stale', 'unconfirmed', False),
    ('unavailable', 'unavailable', False),
])
async def test_detail_separates_audited_custody_and_opening_authority(monkeypatch, change, verification, allowed):
    from fastapi import HTTPException

    detail = inventory['L09.intake'].load('routes.py:detail')
    routes = sys.modules[detail.__module__]
    actor, org, order, receipt, watch, quote = map(uid, range(1, 7))
    maintenance_request = uid(7)
    received = datetime.now(timezone.utc) - timedelta(minutes=1)
    facts = current.OpeningAuthority(
        actor_id=actor, organization_id=org, order_id=order, receipt_id=receipt,
        receipt_revision=1, watch_id=watch, watch_revision=1, incident_revision=0,
        received_at=received, current=True, assigned=True, permission=True,
        customer_opening_permission=True, accepted_assessment_fee=True,
        customer_no_polish_acknowledged=True, consent_revision=1, accepted_terms_revision=1,
        quote_id=quote, quote_revision=1, accepted_fee_minor=500, currency='USD')
    private = dict(currency='USD', fee_minor=500, diagnostic_opening_permission=True,
                   fee_acknowledged=True, no_polish_acknowledged=True, serial='test-serial',
                   reference='test-reference', movement='Automatic', reported_issue='Inspection needed',
                   received_condition='Received', accessories='', assessed_issue='')

    class Transaction:
        async def fetchrow(self, query, *args):
            linked_request = None if change in ('missing_link', 'other_journey') else maintenance_request
            if 'FROM maintenance_received_cases' in query:
                assert args == (uid(8),)
                if linked_request:
                    return dict(request_id=linked_request,
                                fee_quote_id=uid(10) if change == 'wrong_fee_quote' else quote,
                                fee_quote_revision=1)
                return None
            return dict(state='received', order_id=order, custody_receipt_id=receipt,
                        custody_revision=1, received_at=received, private_record=json.dumps(private),
                        maintenance_request_id=linked_request)

    @asynccontextmanager
    async def acquire():
        yield Transaction()

    async def organization(*args):
        return org

    async def record_access(*args):
        return None

    calls = []

    async def read_receipt(body, organization_id, request):
        calls.append(('custody', body.custody_receipt_id, body.order_id, organization_id))
        if change == 'unavailable':
            raise HTTPException(503)
        if change == 'custody_stale':
            raise routes.PublicError('custody_unconfirmed', 'Custody is unconfirmed.', status=409)
        return SimpleNamespace(revision=2 if change == 'revision' else 1,
            received_at=received - timedelta(seconds=1) if change == 'received_at' else received)

    async def read_opening(body, actor_id, organization_id, request, audited):
        calls.append(('opening', actor_id, organization_id, audited.revision))
        if change == 'opening_unavailable':
            raise HTTPException(503)
        if change == 'opening_stale':
            raise routes.PublicError('custody_scope_mismatch', 'Custody differs.', status=409)
        signed_request = {'other_journey': None, 'missing_signed_request': None, 'other_request': uid(9)}
        return facts.model_copy(update={'permission': change != 'permission',
            'maintenance_request_id': signed_request.get(change, maintenance_request)})

    async def verify_submission(request, tx, opening, request_id, *, commitment=None):
        assert request_id == maintenance_request
        return {'id': maintenance_request, 'actor_id': uid(11)}

    monkeypatch.setattr('service_app.received_case.verify_submission', verify_submission)

    monkeypatch.setattr(routes, 'organization', organization)
    monkeypatch.setattr(routes, 'record_access', record_access)
    monkeypatch.setattr(routes, 'receipt_for', read_receipt)
    monkeypatch.setattr(routes, 'assigned_opening', read_opening)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        pool=SimpleNamespace(acquire=acquire))))
    result = await detail(uid(8), request, SimpleNamespace(actor=SimpleNamespace(subject_id=actor)))
    assert result['custody_verification'] == verification
    assert result['diagnosis_allowed'] is allowed
    assert calls == [('custody', receipt, order, org)] + (
        [('opening', actor, org, 1)] if verification == 'current' else [])



@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 409])
async def test_intake_uses_the_audited_orders_receipt(monkeypatch, status):
    from httpx import Response
    from bt_contracts_core.errors import PublicError

    read = inventory['L09.intake'].load('routes.py:receipt_for')
    routes = sys.modules[read.__module__]
    receipt_id, order, org = map(uid, range(1, 4))
    received_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    request = SimpleNamespace(app=object(), headers={'Authorization': 'Bearer test-custody'})

    class Orders:
        async def request(self, method, path, *, headers):
            assert (method, path) == ('GET', f'/v1/custody/receipts/{receipt_id}')
            assert headers == {'Authorization': 'Bearer test-custody'}
            return Response(status, json={
                'id': str(receipt_id), 'order_id': str(order), 'organization_id': str(org),
                'revision': 2, 'received_at': received_at.isoformat(), 'valid': True,
            })

    monkeypatch.setattr(routes, 'clients', lambda app: {'orders': Orders()})
    body = SimpleNamespace(custody_receipt_id=receipt_id, order_id=order)
    if status == 409:
        with pytest.raises(PublicError, match='custody_unconfirmed'):
            await read(body, org, request)
    else:
        receipt = await read(body, org, request)
        assert (receipt.id, receipt.revision, receipt.received_at) == (receipt_id, 2, received_at)


@pytest.mark.asyncio
async def test_operation_lookup_rechecks_retained_watch_ownership(monkeypatch, database_url):
    from bt_runtime.app.db import create_pool
    from bt_runtime.app.settings import Settings
    from httpx import ASGITransport, AsyncClient
    from service_app.main import create_app

    module = inventory['L17.maintenance-requests']
    provider_type = module.load('provider.py:Provider')
    provider_module = sys.modules[provider_type.__module__]
    body = request()
    facts_provider = Provider()

    async def buyer(_):
        return body.actor_id

    async def admission(_, name, *scope):
        assert name == 'maintenance_admission'
        assert scope == (body.actor_id, body.watch_id, body.organization_id,
                         body.operation_id, body.intervention)
        facts = await facts_provider.current(body)
        del facts['private_refs_current']
        return facts

    async def business(*_):
        return {'revision': body.capability_revision}

    monkeypatch.setattr(provider_module, 'prerequisite', admission)
    monkeypatch.setattr(provider_module, 'official_business', business)
    app = create_app(Settings(database_url=database_url, modules_path=MODULES))
    app.state.maintenance_identity = buyer
    app.state.pool = await create_pool(database_url)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            path = f'/v1/maintenance/operations/{body.operation_id}'
            params = {'organization_id': str(body.organization_id)}
            assert (await client.get(path, params=params)).status_code == 404
            submitted = await client.post('/v1/maintenance/requests', json=body.model_dump(mode='json'))
            assert submitted.status_code == 201
            assert (await client.get(path, params=params)).json() == submitted.json()
            assert (await client.get(path, params={'organization_id': str(uid(99))})).status_code == 404

            facts_provider.facts['watch_owned'] = False
            assert (await client.get(path, params=params)).status_code == 403

            facts_provider.facts.update(watch_owned=True, watch_revision=body.watch_revision + 1,
                                        commitment_available=False)
            assert (await client.get(path, params=params)).json() == submitted.json()
    finally:
        await app.state.pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('override', 'allowed'), [
    ({}, True),
    ({'watch_owned': False}, False),
    ({'watch_id': uid(99)}, False),
    ({'organization_id': uid(99)}, False),
    ({'operation_id': uid(99)}, False),
])
async def test_operation_authority_binds_current_ownership(monkeypatch, override, allowed):
    provider_type = inventory['L17.maintenance-requests'].load('provider.py:Provider')
    module = sys.modules[provider_type.__module__]
    body = request()
    scope = (body.actor_id, body.watch_id, body.organization_id, body.operation_id, body.intervention)

    async def admission(_, name, *bindings):
        assert name == 'maintenance_admission'
        assert bindings == scope
        facts = await Provider().current(body)
        del facts['private_refs_current']
        return facts | override

    monkeypatch.setattr(module, 'prerequisite', admission)
    provider = provider_type(None)
    assert await provider.operation_access(body.actor_id, body.organization_id, body.operation_id,
                                           body.watch_id, body.intervention) is allowed
