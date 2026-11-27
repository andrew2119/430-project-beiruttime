"""Pure contracts, authorization boundaries and durable-receipt adapter checks."""
import asyncio
import ast
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
from unittest.mock import patch
import unittest
from bt_runtime.modules import Module, discover
import sys
from uuid import UUID
from pydantic import ValidationError
from bt_contracts.service.intake import current
from bt_contracts.service.intake.intake_command import AssessmentCustody, IntakeOperationCommand, OpeningAcceptance

ROOT = Path(__file__).resolve().parents[4]

def load(path):
    spec = spec_from_file_location(path.replace('/', '_'), ROOT / path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

contract = load('packages/contracts-service/maintenance/v1.py')
lines = load('packages/contracts-service/case-lines/v1.py')
sys.modules['bt_contracts.service.maintenance.v1'] = contract

maintenance_module = Module('L17.maintenance-requests',
    ROOT / 'services/service-operations/modules/maintenance-requests', (), (), None, {}, {}, ())
commands = sys.modules[maintenance_module.load('commands.py:submit').__module__]
authority = load('services/service-operations/modules/intake/authority.py')

intake_module = discover(ROOT/'services/service-operations/modules/intake')[0]
access = sys.modules[intake_module.load('access.py:record_access').__module__]


def retained_terms():
    return lines.RetainedTerms(
        lead_time={'en': 'Five business days', 'ar': 'خمسة أيام عمل'},
        fees={'en': 'Assessment fee: USD 50.00', 'ar': 'رسم التقييم: ٥٠ دولاراً أمريكياً'},
        return_terms={'en': 'Collect the watch at the intake location', 'ar': 'استلم الساعة من موقع الاستلام'},
        assurance={'en': 'Assessment covers the movement', 'ar': 'يشمل التقييم الحركة'},
        conditions={'en': 'Collection requires a custody handover', 'ar': 'يتطلب الاستلام تسليم الحيازة'},
    )


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

    async def operation_access(self, actor, organization, operation, watch=None, intervention=None, brand=None):
        return self.facts.get('identity_current') is True and self.facts.get('watch_owned') is True


class Store:
    def __init__(self):
        self.operations = {}
        self.writes = []

    @asynccontextmanager
    async def transaction(self, key):
        yield self

    async def fetchrow(self, sql, *args):
        return self.operations.get(args[0])

    async def fetchval(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        self.writes.append((sql, args))
        if 'INSERT INTO maintenance_request_operations' in sql:
            self.operations[args[0]] = {'request_hash': args[3], 'result': args[4]}


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
            (uid(2), Provider(assessment_supported=False), 'destination_ineligible'),
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
        for changes in ({'capability_revision':4}, {'watch_revision':3}, {'policy_revision':2},
                        {'assessment_supported':False,'business_active':False}):
            replay = await commands.submit(request(), actor_id=uid(2), provider=Provider(**changes), transaction=store.transaction)
            self.assertEqual(replay, original)
        self.assertEqual(len(store.writes), 3)

    async def test_admission_checks_authority_after_waiting_for_operation_lock(self):
        for changes, expected in [({'identity_current': False}, 'denied'),
                                  ({'capability_revision': 4}, 'stale')]:
            store = Store()
            provider = Provider()
            waiting = asyncio.Event()
            release = asyncio.Event()

            @asynccontextmanager
            async def transaction(operation_id):
                self.assertEqual(operation_id, uid(1))
                waiting.set()
                await release.wait()
                yield store

            attempt = asyncio.create_task(commands.submit(
                request(), actor_id=uid(2), provider=provider, transaction=transaction))
            await waiting.wait()
            provider.facts.update(changes)
            release.set()
            with self.assertRaisesRegex(commands.Rejected, expected):
                await attempt
            self.assertEqual(store.writes, [])

    async def test_watch_commitment_blocks_new_admission_and_preserves_existing_receipt(self):
        store = Store()
        body = request()
        blocked = Provider(commitment_available=False)
        with self.assertRaisesRegex(commands.Rejected, '^watch_committed$'):
            await commands.submit(body, actor_id=uid(2), provider=blocked, transaction=store.transaction)
        self.assertEqual(store.writes, [])
        original = await commands.submit(body, actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        self.assertEqual(await commands.submit(
            body, actor_id=uid(2), provider=blocked, transaction=store.transaction), original)
        self.assertEqual(len(store.writes), 3)

    async def test_closed_operation_rejects_delayed_admission(self):
        class ClosedStore(Store):
            async def fetchval(self, sql, *args):
                self.read_binding = args
                return 1

        store = ClosedStore()
        with self.assertRaisesRegex(commands.Rejected, 'operation_conflict'):
            await commands.submit(request(), actor_id=uid(2), provider=Provider(), transaction=store.transaction)
        self.assertEqual(store.read_binding, (uid(1), uid(2), uid(3)))
        self.assertEqual(store.writes, [])

    async def test_photo_attachment_commits_with_the_request_or_rolls_back(self):
        body = request(photo_refs=[uid(10)])
        for decision in (False, True):
            with self.subTest(decision=decision):
                store = Store()
                provider = Provider()
                attachments = []

                @asynccontextmanager
                async def transaction(key):
                    try:
                        yield store
                    except Exception:
                        store.writes.clear()
                        attachments.clear()
                        raise

                async def attach(tx, command, request_id):
                    self.assertIs(tx, store)
                    self.assertEqual(command, body)
                    self.assertEqual(len(store.writes), 1)
                    self.assertEqual(store.writes[0][1][0], request_id)
                    attachments.extend(command.photo_refs)
                    if isinstance(decision, Exception):
                        raise decision
                    return decision

                from unittest.mock import patch
                with patch.object(commands, 'attach', attach):
                    if decision is True:
                        receipt = await commands.submit(
                            body, actor_id=uid(2), provider=provider, transaction=transaction)
                        self.assertEqual(receipt['state'], 'submitted')
                        self.assertEqual(attachments, body.photo_refs)
                        self.assertEqual(len(store.writes), 3)
                        self.assertEqual(await commands.submit(
                            body, actor_id=uid(2), provider=provider, transaction=transaction), receipt)
                        self.assertEqual(attachments, body.photo_refs)
                    else:
                        code = 'photo_unavailable'
                        with self.assertRaisesRegex(commands.Rejected, code):
                            await commands.submit(body, actor_id=uid(2), provider=provider, transaction=transaction)
                        self.assertEqual(store.writes, [])
                        self.assertEqual(store.operations, {})
                        self.assertEqual(attachments, [])

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
        for status, expected in ((401, 401), (403, 403), (404, 503), (502, 503)):
            async def assignment_failure(*args):
                raise HTTPException(status)

            request.app.state.intake_assignments = N(record_access=assignment_failure)
            with self.assertRaises(HTTPException) as failure:
                await access.record_access(p, request, uid(3), uid(7), 'read')
            self.assertEqual(failure.exception.status_code, expected)
            if expected == 503:
                self.assertEqual(failure.exception.detail, 'intake_assignment_unavailable')
        del request.app.state.intake_assignments
        for change in ({'allowed':False},{'actor_id':uid(8)},{'organization_id':uid(8)},{'order_id':uid(8)}):
            old=value.copy()
            value.update(change)
            with self.assertRaises(HTTPException) as error:
                await access.record_access(p,request,uid(3),uid(7),'read')
            self.assertEqual(error.exception.status_code,403)
            value.clear()
            value.update(old)
        class UnavailableProvider:
            async def record_access(self, *args):
                raise TimeoutError
            async def readable_orders(self, *args):
                raise TimeoutError
        request.app.state.intake_current_authority=UnavailableProvider()
        for check in (access.readable_orders(p,request,uid(3)),
                      access.record_access(p,request,uid(3),uid(7),'write')):
            with self.assertRaises(HTTPException) as unavailable:
                await check
            self.assertEqual(unavailable.exception.status_code,503)
        request.app.state.intake_assignments=N()
        for check in (access.record_access(p,request,uid(3),uid(7),'read'),
                      access.record_access(p,request,uid(3),uid(7),'write'),
                      access.readable_orders(p,request,uid(3))):
            with self.assertRaises(HTTPException) as unavailable:
                await check
            self.assertEqual(unavailable.exception.status_code,503)


    async def test_active_queue_excludes_legacy_rows_and_uses_the_same_scope_for_empty_page_totals(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch

        records = intake_module.load('current_routes.py:records')
        routes = sys.modules[records.__module__]
        org, order = uid(2), uid(3)

        class Tx:
            async def fetch(tx, sql, *args):
                self.assertIn("private_record->>'currency'='USD'", sql)
                self.assertIn('count(*) OVER ()', sql)
                self.assertEqual(args[:2], (org, [order]))
                return [{'id': uid(4), 'total': 1}] if args[2] == 0 else []

            async def fetchval(tx, sql, *args):
                self.assertIn("private_record->>'currency'='USD'", sql)
                self.assertEqual(args, (org, [order]))
                return 1

        @asynccontextmanager
        async def acquire():
            yield Tx()

        async def selected_org(*args):
            return org

        async def assigned_orders(*args):
            return [order]

        req = N(app=N(state=N(pool=N(acquire=acquire))))
        with patch.multiple(routes, organization=selected_org, readable_orders=assigned_orders):
            self.assertEqual(await records(req, None), {
                'intake_contract': 'current', 'items': [{'id': uid(4)}], 'total': 1, 'next_offset': None,
            })
            self.assertEqual(await records(req, None, offset=50), {
                'intake_contract': 'current', 'items': [], 'total': 1, 'next_offset': None,
            })


    async def test_default_assignment_client_requires_current_scoped_orders_facts(self):
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace as N
        from unittest.mock import patch
        import httpx
        from fastapi import HTTPException
        from bt_bulkheads import DependencyClient

        actor, org, order = (uid(n) for n in range(2, 5))
        changed = {}
        paths = []

        def assignment(request):
            paths.append(request.url.path)
            self.assertEqual(request.headers['authorization'], 'Bearer test-service')
            self.assertEqual(request.url.params['organization_id'], str(org))
            self.assertEqual(request.url.params['actor_id'], str(actor))
            value = dict(actor_id=str(actor), organization_id=str(org), assignment_revision=1)
            if request.url.path.endswith('/intake-record-access'):
                permission = request.url.params['permission']
                value.update(order_id=str(order), permission=permission, allowed=True)
            else:
                value['order_ids'] = [str(order)]
            return httpx.Response(200, json=value | changed)

        orders = DependencyClient('orders', 'http://example.test', transport=httpx.MockTransport(assignment))
        req = N(app=N(state=N()), headers={'Authorization': 'Bearer test-staff'})
        principal = N(actor=N(subject_id=actor))
        try:
            with TemporaryDirectory() as folder:
                old_snapshot = Path(folder) / 'assignments.json'
                old_snapshot.write_text(json.dumps({'revision': 1, 'grants': [{
                    'actor_id': str(actor), 'organization_id': str(org), 'order_id': str(order),
                    'permissions': ['read', 'write'],
                }]}))
                with patch.dict('os.environ', {'BT_INTAKE_ASSIGNMENTS_FILE': str(old_snapshot)}), \
                        patch('service_app.sources.client', return_value=orders), \
                        patch('service_app.sources.service_headers', return_value={'Authorization': 'Bearer test-service'}):
                    self.assertEqual(await access.readable_orders(principal, req, org), [order])
                    self.assertTrue((await access.record_access(principal, req, org, order, 'write')).allowed)
                    changed.update(assignment_revision=2, order_ids=[])
                    self.assertEqual(await access.readable_orders(principal, req, org), [])
                    changed.pop('order_ids')
                    changed['allowed'] = False
                    for permission in ('read', 'write'):
                        with self.assertRaises(HTTPException) as denied:
                            await access.record_access(principal, req, org, order, permission)
                        self.assertEqual(denied.exception.status_code, 403)
                    changed['allowed'] = 'true'
                    with self.assertRaises(HTTPException) as unavailable:
                        await access.record_access(principal, req, org, order, 'write')
                    self.assertEqual(unavailable.exception.status_code, 503)
        finally:
            await orders.aclose()
        self.assertEqual(paths[:2], ['/internal/v1/intake-readable-orders', '/internal/v1/intake-record-access'])

    async def test_assigned_intake_can_record_reported_symptoms_before_custody(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from fastapi import HTTPException

        save = intake_module.load('current_routes.py:save')
        routes = sys.modules[save.__module__]
        fixtures = json.loads((ROOT / 'packages/contracts-service/intake/assignment-fixtures.json').read_text())
        write = fixtures['write']
        actor, org, order = (UUID(write[key]) for key in ('actor_id', 'organization_id', 'order_id'))
        caller = N(actor=N(subject_id=actor))
        writes = []
        events = []
        allowed = True

        class Assignment:
            async def record_access(self, *args):
                permission = args[-1]
                if args != (actor, org, order, permission):
                    raise AssertionError('Unexpected assignment scope')
                return fixtures[permission if allowed else 'revoked']

            async def readable_orders(self, *args):
                if args != (actor, org):
                    raise AssertionError('Unexpected queue scope')
                return fixtures['list']

        class Tx:
            async def fetchrow(self, *args):
                return None

            async def execute(self, sql, *args):
                if 'INSERT' in sql:
                    writes.append((sql, args))

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Tx()

        async def organization(*args):
            return org

        async def enqueue(tx, event, destinations):
            events.append(event)

        req = N(headers={'Idempotency-Key':'test-new-intake'}, url=N(path='/v1/intake/records'),
            state=N(request_id='test-intake'), app=N(state=N(pool=None, intake_assignments=Assignment())))
        body = routes.Intake(order_id=order, serial='Private serial', reference='Watch reference',
            movement='Mechanical', received_condition='Worn', accessories='',
            reported_issue='Private reported symptom', assessed_issue='',
            diagnostic_opening_permission=False, no_polish_acknowledged=False,
            fee_acknowledged=False, fee_minor=0, currency='USD')

        with patch.multiple(routes, unit_of_work=transaction, organization=organization, enqueue=enqueue):
            result = await save(body, req, caller)
            self.assertEqual(result['state'], 'awaiting_intake')
            self.assertFalse(result['diagnosis_allowed'])
            self.assertIsNone(result['work_result'])
            self.assertEqual(len(writes), 3)
            self.assertEqual(await access.readable_orders(caller, req, org), [order])
            self.assertTrue((await access.record_access(caller, req, org, order, 'read')).allowed)
            self.assertNotIn(body.reported_issue, events[0].model_dump_json())
            allowed = False
            with self.assertRaises(HTTPException) as denied:
                await save(body, req, caller)
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(len(writes), 3)


    def intake_router(self):
        return intake_module.load('entrypoint.py:router')

    def test_intake_registers_one_contract_at_startup(self):
        self.assertEqual(intake_module.routes, ('entrypoint.py:router',))
        self.assert_intake_routes(self.intake_router(), ('current_routes', 'current_evidence'))

    def routes_under(self, router):
        for route in router.routes:
            if hasattr(route, 'original_router'):
                yield from self.routes_under(route.original_router)
            else:
                yield route

    def assert_intake_routes(self, router, expected):
        routes = list(self.routes_under(router))
        registered = [(method, route.path) for route in routes for method in route.methods if route.path.startswith('/v1/intake/')]
        self.assertEqual(len(registered), len(set(registered)))
        for route in routes:
            if not route.path.startswith('/v1/intake/'):
                continue
            self.assertIn(route.endpoint.__module__.rsplit('.', 1)[-1],
                          expected)
        self.assertTrue({
            ('GET', '/v1/intake/records'), ('POST', '/v1/intake/records'),
            ('GET', '/v1/intake/records/{record_id}'), ('PUT', '/v1/intake/records/{record_id}'),
            ('GET', '/v1/intake/records/{record_id}/evidence'), ('POST', '/v1/intake/records/{record_id}/evidence'),
            ('GET', '/v1/intake/evidence/{evidence_id}'),
        }.issubset(registered))

    async def test_intake_registration_requires_current_assignment_for_preparation(self):
        import httpx
        from fastapi import FastAPI
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        actor, org, order = map(uid, (1, 2, 3))
        records = sys.modules[intake_module.load('current_routes.py:create').__module__]

        async def identity(method, path, **kwargs):
            self.assertEqual((method, path), ('GET', '/internal/v1/principal'))
            return httpx.Response(200, json={
                'actor': {'subject_id': str(actor), 'organization_id': str(org), 'session_id': 'test-staff'},
                'roles': [], 'permissions': [], 'organizations': [str(org)],
                'organization_grants': [{
                    'organization_id': str(org), 'roles': ['technical_staff'],
                    'permissions': ['business.jobs.write'],
                }],
            })

        async def directory(method, path, **kwargs):
            self.assertEqual((method, path), ('GET', f'/v1/directory/providers/{org}'))
            return httpx.Response(200, json={
                'organization_id': str(org), 'official': True, 'active': True, 'kind': 'dealer',
            })

        orders = AsyncMock(return_value=httpx.Response(404))
        tx = SimpleNamespace(fetchrow=AsyncMock(return_value=None),
                             fetchval=AsyncMock(return_value=None), execute=AsyncMock())

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertIn('test-preparation', lock_key)
            yield tx

        dependencies = {
            'identity': SimpleNamespace(request=identity),
            'service-operations': SimpleNamespace(request=directory),
            'orders': SimpleNamespace(request=orders),
        }

        async def prepare(router, handler, **body_changes):
            app = FastAPI()
            app.include_router(router)
            app.state.pool = None
            app.state.intake_clients = dependencies

            @app.middleware('http')
            async def request_context(request, call_next):
                request.state.request_id = 'test-preparation'
                return await call_next(request)

            with patch.multiple(handler, unit_of_work=transaction, enqueue=AsyncMock()), \
                    patch('service_app.sources.client', return_value=dependencies['orders']), \
                    patch('service_app.sources.service_headers', return_value={'Authorization': 'Bearer test-service'}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://example.test') as client:
                    return await client.post('/v1/intake/records', headers={
                        'Authorization': 'Bearer test-staff', 'Idempotency-Key': 'test-preparation',
                    }, json={
                        'order_id': str(order), 'serial': 'Private serial', 'reference': 'Watch reference',
                        'movement': 'Mechanical', 'received_condition': 'Worn', 'accessories': '',
                        'reported_issue': 'Running slow', 'assessed_issue': '',
                        'diagnostic_opening_permission': False, 'no_polish_acknowledged': False,
                        'fee_acknowledged': False, 'fee_minor': 0, 'currency': 'USD',
                    } | body_changes)

        response = await prepare(self.intake_router(), records)
        self.assertEqual(response.status_code, 503, response.text)
        orders.assert_awaited_once()
        tx.execute.assert_awaited_once_with(
            'SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'intake-order:{org}:{order}')
        tx.fetchrow.assert_not_awaited()

        tx.execute.reset_mock()
        orders.reset_mock()
        orders.return_value = httpx.Response(200, json={
            'actor_id': str(actor), 'organization_id': str(org), 'order_id': str(order),
            'permission': 'write', 'assignment_revision': 1, 'allowed': True,
        })
        response = await prepare(self.intake_router(), records)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['state'], 'awaiting_intake')
        self.assertIs(response.json()['diagnosis_allowed'], False)
        orders.assert_awaited_once()
        self.assertTrue(any('INSERT INTO technical_intakes' in call.args[0]
                            for call in tx.execute.await_args_list))

    def test_current_intake_exposes_assigned_records_evidence_and_recovery(self):
        router = self.intake_router()
        self.assert_intake_routes(router, ('current_routes', 'current_evidence'))
        recovery = {(route.path, method) for route in self.routes_under(router) for method in route.methods}
        self.assertTrue({
            ('/v1/intake/operations/{key}', 'GET'),
            ('/v1/intake/operations/{key}', 'DELETE'),
        }.issubset(recovery))

    async def test_current_intake_http_requires_current_assignment_custody_and_opening(self):
        from base64 import b64encode
        from io import BytesIO
        from unittest.mock import patch

        import httpx
        from PIL import Image, PngImagePlugin
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from bt_contracts_core.errors import PublicError
        from bt_bulkheads import DependencyClient

        routes = sys.modules[intake_module.load('current_routes.py:save').__module__]
        fixtures = json.loads((ROOT / 'packages/contracts-service/intake/assignment-fixtures.json').read_text())
        grant = fixtures['write']
        actor, org, order = (grant[key] for key in ('actor_id', 'organization_id', 'order_id'))
        assignment = None
        read_revoked = False
        queue_available = False
        record_hidden = False
        writes = []
        events = []
        stored_evidence = []
        record = None
        receipts = {}
        custody_current = True
        custody_available = True
        current_incident_revision = 0
        receipt_revision = 1
        opening_allowed = True
        receipt, watch, quote = (uid(n) for n in (5, 6, 7))
        received_at = datetime(2026, 11, 16, tzinfo=timezone.utc)
        acceptance = dict(quote_id=str(quote), quote_revision=1, accepted_terms_revision=2,
                          consent_revision=3)
        receipt_facts = dict(actor_id=actor, organization_id=org, order_id=order,
                             received_at=received_at, watch_id=watch, current_watch_id=watch,
                             watch_revision=1, current_watch_revision=1, incident_revision=0,
                             current_incident_revision=0)

        class CurrentAuthority:
            async def current(self, *binding):
                self_test.assertEqual(binding, (UUID(actor), UUID(org), UUID(order)))
                return dict(receipt_facts, **acceptance, receipt_id=receipt, receipt_revision=receipt_revision,
                            current=True, assigned=True, permission=True,
                            customer_opening_permission=opening_allowed, accepted_assessment_fee=True,
                            customer_no_polish_acknowledged=True, accepted_fee_minor=2500, currency='USD')

        self_test = self

        def upstream(request):
            if request.url.path == '/internal/v1/principal':
                return httpx.Response(200, json={
                    'actor': {'subject_id': actor, 'organization_id': org, 'session_id': 'test-staff'},
                    'roles': ['dealer'], 'permissions': [], 'organizations': [org],
                    'organization_grants': [{'organization_id': org, 'roles': ['technical_staff'],
                        'permissions': ['business.jobs.write', 'business.records.read']}],
                })
            if request.url.path == f'/v1/directory/providers/{org}':
                return httpx.Response(200, json={
                    'organization_id': org, 'official': True, 'active': True, 'kind': 'dealer',
                })
            self.fail('Intake contacted an unexpected identity or directory endpoint')

        def orders_assignments(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.url.params['organization_id'], org)
            self.assertEqual(request.url.params['actor_id'], actor)
            self.assertEqual(request.headers['Authorization'], 'Bearer test-service')
            if request.url.path == '/internal/v1/intake-readable-orders':
                if read_revoked:
                    return httpx.Response(403)
                return httpx.Response(200, json=fixtures['list']) if queue_available else httpx.Response(404)
            self.assertEqual(request.url.path, '/internal/v1/intake-record-access')
            self.assertEqual(request.url.params['order_id'], order)
            permission = request.url.params['permission']
            self.assertIn(permission, ('read', 'write', 'assess'))
            if permission == 'read' and read_revoked:
                return httpx.Response(403)
            if permission == 'assess':
                return httpx.Response(200, json=fixtures['read'] | {'permission': 'assess'})
            grant = assignment if permission == 'write' else fixtures['read']
            return httpx.Response(200, json=grant) if grant else httpx.Response(404)

        class Transaction:
            async def fetch(self, statement, organization, order_ids, offset):
                self_test.assertEqual((organization, order_ids, offset), (UUID(org), [UUID(order)], 0))
                return [dict(id=record['id'], order_id=record['order_id'], state=record['state'],
                             revision=record['revision'], total=1)]

            async def fetchrow(self, statement, *args):
                if 'FROM technical_intake_operations WHERE' in statement:
                    return receipts.get(args)
                if 'FROM technical_intake_operations o' in statement:
                    prior = receipts.get(args)
                    return prior | {'order_id': record['order_id'], 'record_id': record['id']} if prior else None
                return record if 'FROM technical_intakes' in statement and not record_hidden else None

            async def fetchval(self, statement, *args):
                if 'to_regclass' in statement:
                    return False
                if 'count(*) FROM technical_intake_evidence' in statement:
                    return 0
                if 'FROM technical_intake_evidence' in statement:
                    return None
                return record and record['id']

            async def execute(self, statement, *args):
                nonlocal record
                if statement.startswith('INSERT INTO technical_intakes'):
                    record = dict(zip(('id', 'organization_id', 'order_id', 'author_id', 'revision',
                                       'state', 'custody_receipt_id', 'custody_revision', 'received_at',
                                       'private_record'), args, strict=True))
                elif statement.startswith('INSERT INTO technical_intake_evidence'):
                    stored_evidence.append(args[5])
                elif statement.startswith('UPDATE technical_intakes SET revision=$2'):
                    record['revision'] = args[1]
                elif statement.startswith('UPDATE technical_intakes'):
                    record.update(zip(('revision', 'state', 'custody_receipt_id', 'custody_revision',
                                       'received_at', 'private_record'), args[2:], strict=True))
                elif statement.startswith('INSERT INTO technical_intake_operations'):
                    receipts[args[:3]] = {'request_hash': args[3], 'result': args[4]}
                if statement.startswith(('INSERT', 'UPDATE')):
                    writes.append(statement)

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Transaction()

        async def enqueue(tx, event, destinations):
            events.append(event.data['state'])
            self.assertNotIn('reported_issue', event.data)

        from types import SimpleNamespace

        dependencies = {
            name: DependencyClient(name, 'http://example.test', transport=httpx.MockTransport(handler))
            for name, handler in {
                'identity': upstream, 'service-operations': upstream, 'orders': orders_assignments,
            }.items()
        }

        async def source_custody(*binding):
            self.assertEqual(binding, (UUID(actor), UUID(org), UUID(order), UUID(str(receipt))))
            if not custody_available:
                raise ConnectionError('unavailable')
            if not custody_current:
                return False
            return receipt_facts | {'id': receipt, 'revision': receipt_revision, 'valid': True,
                                    'current_incident_revision': current_incident_revision}

        def mount():
            app = FastAPI()
            router = self.intake_router()
            app.state.intake_current_custody = source_custody
            self.assert_intake_routes(router, ('current_routes', 'current_evidence'))
            app.include_router(router)
            app.state.pool = SimpleNamespace(acquire=transaction)
            app.state.intake_clients = dependencies

            @app.exception_handler(PublicError)
            async def public_error(request, error):
                return JSONResponse({'error': {'code': error.code}}, status_code=error.status)

            @app.middleware('http')
            async def request_context(request, call_next):
                request.state.request_id = 'test-intake-cutover'
                return await call_next(request)

            return app

        app = mount()
        body = dict(order_id=order, serial='Private serial', reference='Watch reference',
                    movement='Mechanical', received_condition='Worn', accessories='',
                    reported_issue='Private reported symptom', assessed_issue='',
                    diagnostic_opening_permission=False, no_polish_acknowledged=False,
                    fee_acknowledged=False, fee_minor=0, currency='USD')
        path = f'/v1/intake/records?organization_id={org}&intake_contract=current'
        preparatory_path = f'/v1/intake/records?organization_id={org}'
        headers = {'Authorization':'Bearer test-staff', 'Idempotency-Key':'test-cutover-write'}
        try:
            with patch.multiple(routes, unit_of_work=transaction, enqueue=enqueue), \
                    patch('service_app.sources.client', return_value=dependencies['orders']), \
                    patch('service_app.sources.service_headers', return_value={'Authorization': 'Bearer test-service'}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://example.test') as client:
                    queue_path = preparatory_path + '&intake_contract=describe'
                    unavailable = await client.get(queue_path, headers=headers)
                    self.assertEqual(unavailable.status_code, 503)
                    self.assertEqual(unavailable.json()['detail'], 'intake_assignment_unavailable')
                    queue_available = True
                    # Reuse the original operation through assignment outages and
                    # revocation. None of those responses may reserve the order.
                    for assignment, expected in [
                        (None, 503),
                        (grant | {'assignment_revision': True}, 503),
                        (grant | {'organization_id': str(uid(95))}, 403),
                        (grant | {'order_id': str(uid(96))}, 403),
                        (grant | {'actor_id': str(uid(97))}, 403),
                        (fixtures['revoked'], 403),
                        (grant, 201),
                    ]:
                        response = await client.post(preparatory_path, headers=headers, json=body)
                        self.assertEqual(response.status_code, expected, response.text)
                        if expected == 503:
                            self.assertEqual(response.json()['detail'], 'intake_assignment_unavailable')
                        if expected != 201:
                            self.assertEqual(writes, [])
                            self.assertEqual(events, [])
                            self.assertIsNone(record)
                    self.assertEqual(response.json()['state'], 'awaiting_intake')
                    self.assertIs(response.json()['diagnosis_allowed'], False)
                    self.assertEqual(len(writes), 3)
                    self.assertEqual(events, ['awaiting_intake'])
                    queue = await client.get(queue_path, headers=headers)
                    self.assertEqual(queue.status_code, 200, queue.text)
                    self.assertEqual(queue.json()['intake_contract'], 'current')
                    self.assertEqual(queue.json()['total'], 1)

                    saved = json.loads(record['private_record'])
                    self.assertEqual(saved['reported_issue'], body['reported_issue'])
                    self.assertEqual(saved['assessed_issue'], '')
                    self.assertIs(saved['no_polish_acknowledged'], False)
                    self.assertIs(saved['fee_acknowledged'], False)
                    self.assertEqual(saved['fee_minor'], 0)

                    # Recover over the registered path without resending the private draft.
                    receipt_result = await client.post(preparatory_path, headers=headers, json={
                        'action': 'lookup', 'operation_id': headers['Idempotency-Key'],
                    })
                    self.assertEqual(receipt_result.status_code, 200, receipt_result.text)
                    self.assertEqual(receipt_result.json(), {
                        'kind': 'save', 'operation_id': headers['Idempotency-Key'],
                        'organization_id': org,
                        'record_id': response.json()['id'], 'order_id': order, 'revision': 1,
                    })
                    self.assertEqual(response.json()['operation_id'], headers['Idempotency-Key'])
                    self.assertEqual(response.json()['organization_id'], org)
                    self.assertEqual(response.json()['order_id'], order)
                    retry = await client.post(preparatory_path, headers=headers, json=body)
                    self.assertEqual(retry.json(), response.json())
                    self.assertEqual(len(writes), 3)

                    app.state.intake_current_authority = CurrentAuthority()
                    detail_path = f'/v1/intake/records/{response.json()["id"]}?organization_id={org}&intake_contract=current'
                    queued = await client.get(path, headers=headers)
                    self.assertEqual(queued.status_code, 200, queued.text)
                    self.assertEqual(queued.json()['total'], 1)
                    self.assertNotIn(body['reported_issue'], queued.text)
                    prepared = await client.get(detail_path, headers=headers)
                    self.assertEqual(prepared.status_code, 200, prepared.text)
                    self.assertEqual(prepared.json()['private_record']['reported_issue'], body['reported_issue'])
                    self.assertEqual(prepared.json()['custody_verification'], 'awaiting_intake')
                    read_revoked = True
                    evidence_path = detail_path.replace('?organization_id=', '/evidence?organization_id=')
                    for url in (path, detail_path, evidence_path):
                        unmarked = url.split('&')[0]
                        for read_path in (url, unmarked, unmarked + '&intake_contract=legacy'):
                            denied = await client.get(read_path, headers=headers)
                            self.assertEqual(denied.status_code, 403 if '/records?' in read_path else 404)
                            self.assertNotIn(body['reported_issue'], denied.text)
                    read_revoked = False
                    receive_headers = headers | {'If-Match': '1', 'Idempotency-Key': 'test-cutover-receive'}
                    received = body | {'assessed_issue': '', 'custody_receipt_id': str(receipt), 'opening_acceptance': acceptance,
                                       'diagnostic_opening_permission': True, 'no_polish_acknowledged': True,
                                       'fee_acknowledged': True, 'fee_minor': 2500}

                    evidence_route = intake_module.load('current_evidence.py:upload')
                    evidence = sys.modules[evidence_route.__module__]
                    photo = dict(kind='condition_photo', media_type='image/png', content_base64='AAAA')
                    original_writes = writes.copy()
                    missing_responses = []
                    with patch.object(evidence, 'unit_of_work', transaction):
                        for record_hidden, assignment, status in (
                            (True, grant, 404),
                            (False, fixtures['revoked'], 404),
                            (False, None, 503),
                        ):
                            update = await client.put(detail_path.split('&')[0],
                                                      headers=receive_headers, json=received)
                            upload = await client.post(evidence_path.split('&')[0],
                                                       headers=receive_headers, json=photo)
                            self.assertEqual((update.status_code, upload.status_code), (status, status))
                            self.assertEqual(update.json(), upload.json())
                            if status == 404:
                                missing_responses.append(update.json())
                            else:
                                self.assertEqual(update.json()['detail'], 'intake_assignment_unavailable')
                            self.assertEqual(writes, original_writes)
                            self.assertEqual(events, ['awaiting_intake'])
                    self.assertEqual(missing_responses, [missing_responses[0]] * 2)
                    assignment = grant
                    # Even an assigned writer cannot bypass the declaration on the registered upload path.
                    png_signature = photo | {'content_base64': 'iVBORw0KGgo='}
                    with patch.object(evidence, 'unit_of_work', transaction):
                        for url, status, code in [
                            (evidence_path.removesuffix('&intake_contract=current'), 422, 'safe_photo_required'),
                            (evidence_path, 422, 'safe_photo_required'),
                        ]:
                            rejected = await client.post(url, headers=receive_headers, json=png_signature)
                            self.assertEqual(rejected.status_code, status, rejected.text)
                            self.assertEqual(rejected.json().get('detail') or rejected.json()['error']['code'], code)
                    self.assertEqual(writes, original_writes)


                    custody_available = False
                    unavailable = await client.put(detail_path, headers=receive_headers, json=received)
                    self.assertEqual(unavailable.status_code, 503, unavailable.text)
                    self.assertEqual(writes, original_writes)
                    custody_available = True
                    current_incident_revision = 1
                    mismatched = await client.put(detail_path, headers=receive_headers, json=received)
                    self.assertEqual(mismatched.status_code, 409, mismatched.text)
                    self.assertEqual(mismatched.json()['error']['code'], 'custody_scope_mismatch')
                    self.assertEqual(writes, original_writes)
                    current_incident_revision = 0

                    for custody_current, opening_allowed, code in [
                        (False, True, 'custody_unconfirmed'),
                        (True, False, 'opening_acceptance_unconfirmed'),
                    ]:
                        denied = await client.put(detail_path, headers=receive_headers, json=received)
                        self.assertEqual(denied.status_code, 409, denied.text)
                        self.assertEqual(denied.json()['error']['code'], code)
                        self.assertEqual(events, ['awaiting_intake'])
                        self.assertEqual(len(writes), 3)

                    opening_allowed = True
                    confirmed = await client.put(detail_path, headers=receive_headers, json=received)
                    self.assertEqual(confirmed.status_code, 200, confirmed.text)
                    self.assertEqual(confirmed.json()['state'], 'received')
                    self.assertIs(confirmed.json()['diagnosis_allowed'], True)
                    self.assertEqual(events, ['awaiting_intake', 'received'])
                    stored = receipts[(UUID(actor), UUID(org), receive_headers['Idempotency-Key'])]
                    saved_receipt = json.loads(stored['result'])
                    self.assertNotIn('diagnosis_allowed', saved_receipt)
                    stored['result'] = json.dumps(saved_receipt | {'diagnosis_allowed': True})
                    opening_allowed = False
                    replay = await client.put(detail_path, headers=receive_headers, json=received)
                    self.assertEqual(replay.status_code, 200, replay.text)
                    self.assertEqual(replay.json(), confirmed.json() | {'diagnosis_allowed': False})
                    self.assertEqual(events, ['awaiting_intake', 'received'])

                    for custody_current, opening_allowed, verification, permitted in [
                        (True, True, 'current', True),
                        (True, False, 'current', False),
                        (False, True, 'unconfirmed', False),
                    ]:
                        detail = await client.get(detail_path, headers=headers)
                        self.assertEqual(detail.status_code, 200, detail.text)
                        self.assertEqual(detail.json()['custody_verification'], verification)
                        self.assertIs(detail.json()['diagnosis_allowed'], permitted)
                        self.assertEqual(detail.json()['private_record']['opening_acceptance'], acceptance)

                    custody_current = opening_allowed = True
                    assessment = (await client.get(detail_path, headers=headers)).json()
                    assessed = await client.put(
                        detail_path,
                        json=received | {'assessed_issue': 'Observed wear',
                                         'reviewed_assessment_custody': assessment['current_assessment_custody']},
                        headers=headers | {'If-Match': '2', 'Idempotency-Key': 'test-record-finding'},
                    )
                    self.assertEqual(assessed.status_code, 200, assessed.text)
                    receipt_revision = 2
                    offer = (await client.get(detail_path, headers=headers)).json()
                    report_only = received | {
                        'opening_acceptance': None, 'diagnostic_opening_permission': False,
                        'no_polish_acknowledged': False, 'fee_acknowledged': False, 'fee_minor': 0,
                    }
                    advanced = await client.put(
                        detail_path, json=report_only | {'reviewed_receipt_revision': offer['receipt_revision_for_review']},
                        headers=headers | {'If-Match': '3', 'Idempotency-Key': 'test-advance-receipt'},
                    )
                    self.assertEqual(advanced.status_code, 200, advanced.text)
                    self.assertEqual(advanced.json()['revision'], 4)
                    private = json.loads(record['private_record'])
                    self.assertEqual([entry['receipt_revision'] for entry in private['custody_history']], [1])
                    self.assertEqual([entry['finding'] for entry in private['assessment_history']], ['Observed wear'])

                restarted = mount()
                restarted.state.intake_current_authority = CurrentAuthority()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),
                                             base_url='http://example.test') as client:
                    detail = await client.get(detail_path, headers=headers)
                    self.assertEqual(detail.status_code, 200, detail.text)
                    restored = detail.json()
                    self.assertEqual(restored['custody_verification'], 'current')
                    self.assertFalse(restored['diagnosis_allowed'])
                    self.assertIsNone(restored['private_record']['opening_acceptance'])
                    self.assertEqual(restored['private_record']['assessed_issue'], '')
                    saved = await client.put(
                        detail_path, json=report_only | {'reported_issue': 'Updated reported symptom'},
                        headers=headers | {'If-Match': '4', 'Idempotency-Key': 'test-update-report'},
                    )
                    self.assertEqual(saved.status_code, 200, saved.text)
                    updated = json.loads(record['private_record'])
                    self.assertEqual(updated['custody_history'], private['custody_history'])
                    self.assertEqual(updated['assessment_history'], private['assessment_history'])
                    self.assertEqual(updated['reported_issue'], 'Updated reported symptom')

                    png = BytesIO()
                    metadata = PngImagePlugin.PngInfo()
                    metadata.add_text('Comment', 'test-private-photo-metadata')
                    with Image.new('RGB', (2, 2), 'blue') as image:
                        image.save(png, format='PNG', pnginfo=metadata)
                    photo = {'kind': 'condition_photo', 'media_type': 'image/png',
                             'content_base64': b64encode(png.getvalue()).decode(),
                             'safe_photo_declared': True}
                    before_upload_events = events.copy()
                    upload_headers = headers | {'If-Match': '5', 'Idempotency-Key': 'test-upload-condition'}
                    with patch.object(evidence, 'unit_of_work', transaction):
                        attached = await client.post(evidence_path, headers=upload_headers, json=photo)
                        replay = await client.post(evidence_path, headers=upload_headers, json=photo)
                    self.assertEqual(attached.status_code, 201, attached.text)
                    self.assertEqual(replay.json(), attached.json())
                    self.assertEqual(attached.json()['revision'], 6)
                    self.assertEqual(len(stored_evidence), 1)
                    with Image.open(BytesIO(stored_evidence[0])) as image:
                        self.assertEqual(image.info, {})
                        self.assertEqual(image.convert('RGB').getpixel((0, 0)), (0, 0, 255))
                    self.assertEqual(events, before_upload_events)

                    receipt = str(uid(98))
                    receipt_revision = 3
                    review_path = f'{detail_path}&review_receipt_id={receipt}'
                    assignment = fixtures['revoked']
                    denied = await client.get(review_path, headers=headers)
                    self.assertEqual(denied.status_code, 404, denied.text)
                    assignment = grant
                    offered = await client.get(review_path, headers=headers)
                    self.assertEqual(offered.status_code, 200, offered.text)
                    self.assertNotIn(body['reported_issue'], offered.text)
                    self.assertEqual(offered.json()['revision'], 6)
                    binding = offered.json()['receipt_revision_for_review']
                    self.assertEqual(binding['receipt_id'], receipt)
                    replace_headers = headers | {'If-Match': '6', 'Idempotency-Key': 'test-replace-custody'}
                    replacement = report_only | {'custody_receipt_id': receipt, 'reviewed_receipt_revision': binding}
                    receipt_facts['incident_revision'] = current_incident_revision = 1
                    stale = await client.put(detail_path, headers=replace_headers, json=replacement)
                    self.assertEqual(stale.status_code, 409, stale.text)
                    self.assertEqual(stale.json()['error']['code'], 'stale_receipt_revision')
                    self.assertEqual(events, before_upload_events)
                    fresh = await client.get(review_path, headers=headers)
                    self.assertEqual(fresh.status_code, 200, fresh.text)
                    replacement['reviewed_receipt_revision'] = fresh.json()['receipt_revision_for_review']
                    self.assertEqual(replacement['reviewed_receipt_revision']['incident_revision'], 1)
                    accepted = await client.put(detail_path, headers=replace_headers, json=replacement)
                    self.assertEqual(accepted.status_code, 200, accepted.text)
                    self.assertEqual(accepted.json()['revision'], 7)
                    self.assertEqual(str(record['custody_receipt_id']), receipt)
                    self.assertEqual(events, before_upload_events + ['received'])
        finally:
            for client in dependencies.values():
                await client.aclose()


    async def test_operation_receipt_requires_original_scope_and_current_write_assignment(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from fastapi import HTTPException
        from bt_contracts_core.errors import PublicError
        from bt_runtime.modules import discover

        intake = discover(ROOT/'services/service-operations/modules/intake')[0]
        route = intake.load('current_routes.py:operation_receipt')
        routes = sys.modules[route.__module__]
        key = 'test-original-key'
        actor, org, order, record = (uid(n) for n in range(2, 6))
        stored = {'id': str(record), 'revision': 2, 'diagnosis_allowed': True}

        class Tx:
            async def fetchrow(self, sql, *args):
                if args != (actor, org, key):
                    return None
                return dict(order_id=order, record_id=record, request_hash='test-digest', result=json.dumps(stored))

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertEqual(lock_key, f'intake:{caller.actor.subject_id}:{selected_org}:{key}')
            yield Tx()

        async def organization(p, req, permission):
            self.assertEqual(permission, 'intake.write')
            return selected_org

        class Assignment:
            async def record_access(provider, *args):
                self.assertEqual(args, (actor, org, order, 'write'))
                return dict(actor_id=actor, organization_id=org, order_id=order,
                            permission='write', assignment_revision=2, allowed=allowed)

        req = N(app=N(state=N(pool=None, intake_current_authority=Assignment())))
        caller = N(actor=N(subject_id=actor))
        selected_org = org
        allowed = True
        with patch.multiple(routes, unit_of_work=transaction, organization=organization):
            for kind, payload in [('save', stored), ('evidence', {
                'id': str(uid(7)), 'record_id': str(record), 'revision': 3,
            })]:
                stored = payload
                self.assertEqual(await route(key, req, caller), dict(
                    operation_id=key, organization_id=org, record_id=record, order_id=order,
                    revision=payload['revision'], kind=kind))
            allowed = False
            with self.assertRaises(HTTPException) as denied:
                await route(key, req, caller)
            self.assertEqual(denied.exception.status_code, 403)
            req.app.state.intake_assignments = N()
            with self.assertRaises(HTTPException) as unavailable:
                await route(key, req, caller)
            self.assertEqual(unavailable.exception.status_code, 503)
            for other_actor, other_org in [(uid(9), org), (actor, uid(9))]:
                caller.actor.subject_id, selected_org = other_actor, other_org
                with self.assertRaises(PublicError) as missing:
                    await route(key, req, caller)
                self.assertEqual((missing.exception.status, missing.exception.code), (404, 'operation_missing'))


    async def test_close_serializes_with_admission_and_keeps_committed_receipts(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        import httpx
        from types import SimpleNamespace as N
        from bt_contracts_core.errors import PublicError
        from unittest.mock import AsyncMock, patch

        close = intake_module.load('current_routes.py:close_operation')
        routes = sys.modules[close.__module__]
        actor, org, order, record = (uid(n) for n in range(2, 6))
        p = N(actor=N(subject_id=actor))
        req = N(app=N(state=N(pool=None)))
        stored = {}
        keys = []

        class Tx:
            async def fetchrow(self, sql, *args):
                return stored.get(args)

            async def execute(self, sql, *args):
                if 'ON CONFLICT' not in sql:
                    raise AssertionError('Closure must be idempotent')
                stored[args] = {'request_hash': 'closed'}

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            keys.append(lock_key)
            yield Tx()

        async def organization(*args):
            return org

        async def assigned(*args):
            self.assertEqual(args[0].actor.subject_id, actor)
            self.assertEqual(args[2:], (org, order, 'write'))

        with patch.multiple(routes, unit_of_work=transaction, organization=organization,
                            record_access=assigned):
            for _ in range(2):
                self.assertEqual(await close('test-absent', req, p),
                    {'operation_id': 'test-absent', 'organization_id': org, 'state': 'closed'})
            stored[(actor, org, 'test-committed')] = {
                'request_hash': 'test-digest', 'order_id': order, 'record_id': record,
                'result': json.dumps({'id': str(record), 'revision': 2}),
            }
            receipt = await close('test-committed', req, p)
            self.assertEqual(receipt['record_id'], record)
            self.assertEqual(receipt['revision'], 2)
        stored[(actor, org, 'test-upload')] = {
            'request_hash': 'test-digest', 'order_id': order, 'record_id': record,
            'result': json.dumps({'id': str(uid(6)), 'record_id': str(record), 'revision': 3}),
        }
        app = FastAPI()
        app.include_router(self.intake_router())

        identity = AsyncMock(return_value=httpx.Response(200, json={
            'actor': {'subject_id': str(actor), 'organization_id': str(org), 'session_id': 'test-staff'},
            'roles': [], 'permissions': [], 'organizations': [str(org)],
        }))
        app.state.intake_clients = {'identity': N(request=identity)}

        @app.middleware('http')
        async def request_context(request, call_next):
            request.state.request_id = 'test-recovery'
            return await call_next(request)

        @app.exception_handler(PublicError)
        async def public_error(request, error):
            return JSONResponse({'error': {'code': error.code}}, status_code=error.status)

        with patch.multiple(routes, unit_of_work=transaction, organization=organization,
                            record_access=assigned):
            app.state.pool = None
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='http://example.test',
                                         headers={'Authorization': 'Bearer test-staff'}) as client:
                path = f'/v1/intake/records?organization_id={org}&intake_contract=current'
                command = {'action': 'lookup', 'operation_id': 'test-committed'}
                committed = await client.post(path, json=command)
                self.assertEqual(committed.status_code, 200)
                self.assertEqual(committed.json()['record_id'], str(record))
                self.assertEqual(committed.json()['kind'], 'save')
                upload = await client.post(path, json=command | {'operation_id': 'test-upload'})
                self.assertEqual(upload.status_code, 200)
                self.assertEqual(upload.json()['kind'], 'evidence')
                self.assertEqual(upload.json()['revision'], 3)
                unmarked = await client.post(path.split('&')[0], json=command)
                self.assertEqual(unmarked.json(), committed.json())
                command['operation_id'] = 'test-new-closure'
                missing = await client.post(path, json=command)
                self.assertEqual((missing.status_code, missing.json()['error']['code']),
                                 (404, 'operation_missing'))
                closed = await client.post(path, json=command | {'action': 'close'})
                self.assertEqual(closed.status_code, 200)
                self.assertEqual(closed.json()['state'], 'closed')
        self.assertEqual(keys, [f'intake:{actor}:{org}:test-absent'] * 2 +
                              [f'intake:{actor}:{org}:test-committed'] * 2 +
                              [f'intake:{actor}:{org}:test-upload', f'intake:{actor}:{org}:test-committed'] +
                              [f'intake:{actor}:{org}:test-new-closure'] * 2)


def route_function(name, namespace):
    tree=ast.parse((ROOT/'services/service-operations/modules/intake/current_routes.py').read_text())
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
                return dict(request_hash='digest',result=stored,author_id=uid(2))
            async def execute(self,*args): pass
        @asynccontextmanager
        async def transaction(*args,**kwargs):
            yield Tx()
        async def organization(*args):return uid(3)
        async def record_access(*args,**kwargs):return None
        save=route_function('save',dict(organization=organization,record_access=record_access,
            operation=lambda *args:('original-reference','digest'),PublicError=PublicError,
            unit_of_work=transaction,json=json))
        for provider in (None, N(permission=False)):
            result=await save(N(currency='USD',order_id=uid(7)),
                N(app=N(state=N(pool=None,intake_current_authority=provider))),
                N(actor=N(subject_id=uid(2))))
            self.assertEqual(result, original | {'diagnosis_allowed': False,
                'operation_id': 'original-reference', 'organization_id': str(uid(3)), 'order_id': str(uid(7))})
            self.assertEqual(json.loads(stored),original)

    async def test_customer_grant_and_accepted_fee_are_authoritative(self):
        from types import SimpleNamespace as N
        facts=dict(actor_id=uid(2),organization_id=uid(3),order_id=uid(7),receipt_id=uid(8),
            receipt_revision=2,watch_id=uid(9),watch_revision=1,incident_revision=0,
            current_watch_id=uid(9),current_watch_revision=1,current_incident_revision=0,
            received_at=datetime.now(timezone.utc)-timedelta(seconds=1),current=True,
            assigned=True,permission=True,customer_opening_permission=True,
            accepted_assessment_fee=True,customer_no_polish_acknowledged=True,
            consent_revision=1,accepted_terms_revision=1,quote_id=uid(10),quote_revision=1,
            accepted_fee_minor=5000,currency='USD')
        class Provider:
            async def current(self,*args):
                return facts
        request=N(app=N(state=N(intake_current_authority=Provider())))
        p=N(actor=N(subject_id=uid(2)))
        receipt=N(id=uid(8), order_id=uid(7), organization_id=uid(3), revision=2,
                  watch_id=uid(9), watch_revision=1, incident_revision=0, received_at=facts['received_at'])
        private=dict(currency='USD',fee_minor=5000,diagnostic_opening_permission=True,
            fee_acknowledged=True,no_polish_acknowledged=True)
        opening = intake_module.load('current_routes.py:current_opening')
        self.assertFalse(await opening(receipt,p,request,private,result={}))
        private['opening_acceptance'] = {
            field: facts[field] for field in OpeningAcceptance.model_fields
        }
        self.assertTrue(await opening(receipt,p,request,private,result={}))
        for field in ('customer_opening_permission','accepted_assessment_fee','customer_no_polish_acknowledged','assigned','current'):
            facts[field]=False
            self.assertFalse(await opening(receipt,p,request,private,result={}))
            facts[field]=True
        self.assertFalse(await opening(receipt,p,request,private | {'fee_minor':0},result={}))
        self.assertFalse(await opening(N(**(vars(receipt) | {'revision':3})),p,request,private,result={}))
        for field, replacement in [('quote_id', uid(99)), ('quote_revision', 2),
                                   ('accepted_terms_revision', 2), ('consent_revision', 2)]:
            with self.subTest(field=field):
                saved = facts[field]
                facts[field] = replacement
                result = {}
                self.assertFalse(await opening(receipt,p,request,private,result=result))
                self.assertEqual(result['current_opening_acceptance'][field],
                                 str(replacement) if field == 'quote_id' else replacement)
                facts[field] = saved
        self.assertFalse(await opening(receipt,p,request,private | {
            'opening_acceptance': private['opening_acceptance'] | {'consent_revision': True}
        },result={}))

    async def test_detail_requires_fresh_custody_alongside_opening_authority(self):
        from types import SimpleNamespace as N
        from fastapi import Depends, HTTPException, Request
        from bt_contracts_core.errors import PublicError
        private=dict(currency='USD',fee_minor=5000,diagnostic_opening_permission=True,
            fee_acknowledged=True,no_polish_acknowledged=True)
        row=dict(order_id=uid(7),custody_receipt_id=uid(8),custody_revision=2,
            state='received',private_record=json.dumps(private),author_id=uid(2))
        facts=dict(actor_id=uid(2),organization_id=uid(3),order_id=uid(7),receipt_id=uid(8),
            receipt_revision=2,watch_id=uid(9),watch_revision=1,incident_revision=0,
            current_watch_id=uid(9),current_watch_revision=1,current_incident_revision=0,
            received_at=datetime.now(timezone.utc)-timedelta(seconds=1),current=True,
            assigned=True,permission=True,customer_opening_permission=True,
            accepted_assessment_fee=True,customer_no_polish_acknowledged=True,
            consent_revision=1,accepted_terms_revision=1,quote_id=uid(10),quote_revision=1,
            accepted_fee_minor=5000,currency='USD')
        locked = False

        class Provider:
            async def current(self, *args):
                self_test.assertTrue(locked)
                return facts

        class Tx:
            async def fetchrow(self, sql, *args):
                self_test.assertTrue(locked)
                self_test.assertIn('FOR SHARE', sql)
                return row

        self_test = self

        @asynccontextmanager
        async def transaction(pool):
            nonlocal locked
            locked = True
            try:
                yield Tx()
            finally:
                locked = False

        request=N(app=N(state=N(pool=None,intake_current_authority=Provider())))
        p=N(actor=N(subject_id=uid(2)))
        async def organization(*args):return uid(3)
        async def record_access(*args,**kwargs):return None
        opening = intake_module.load('current_routes.py:current_opening')
        private['opening_acceptance'] = {
            field: str(facts[field]) if field == 'quote_id' else facts[field]
            for field in OpeningAcceptance.model_fields
        }
        row['private_record'] = json.dumps(private)
        # Keep opening facts valid while the independent custody source changes.
        custody = N(id=uid(8), order_id=uid(7), organization_id=uid(3), revision=2,
                    watch_id=uid(9), watch_revision=1, incident_revision=0, received_at=facts['received_at'])
        assessment_custody = sys.modules[opening.__module__].assessment_custody
        private['assessed_issue'] = 'Recorded observation'
        row['private_record'] = json.dumps(private | {'assessment_custody': assessment_custody(custody)})
        for receipt,verification in [(custody,'current'),(N(**(vars(custody) | {'revision': 3})),'unconfirmed'),
                (None,'unconfirmed'),(PublicError('custody_unconfirmed','Unconfirmed',status=409),'unconfirmed'),
                (HTTPException(503),'unavailable')]:
            with self.subTest(verification=verification,receipt=receipt):
                async def receipt_for(*args):
                    self.assertTrue(locked)
                    if isinstance(receipt,Exception):
                        raise receipt
                    return receipt
                async def may_record_assessment(*args):
                    return True
                namespace=dict(assessment_custody=assessment_custody,
                    json=json, may_record_assessment=may_record_assessment, UUID=UUID,Request=Request,Depends=Depends,principal=lambda:None,
                    router=N(get=lambda *args:lambda fn:fn),organization=organization,
                    require_private_assignment=record_access,unit_of_work=transaction,
                    present=lambda value:dict(value,private_record=private.copy(),diagnosis_allowed=False),
                    Intake=N(model_validate=lambda value:value),receipt_for=receipt_for,
                    HTTPException=HTTPException,PublicError=PublicError,current_opening=opening)
                result=await route_function('detail',namespace)(uid(11),request,p)
                self.assertEqual(result['custody_verification'],verification)
                self.assertEqual(result['diagnosis_allowed'],verification=='current')
                if receipt is not None and getattr(receipt, 'revision', None) == 3:
                    self.assertEqual(result['receipt_revision_for_review'], assessment_custody(receipt))
                else:
                    self.assertNotIn('receipt_revision_for_review', result)
                self.assertEqual(result['private_record']['assessed_issue'],
                                 'Recorded observation' if verification == 'current' else '')
                if verification=='current':
                    for field, replacement in [('current_watch_id',uid(12)),
                            ('current_watch_revision',2),('current_incident_revision',1)]:
                        original=facts[field]
                        facts[field]=replacement
                        mismatch=await route_function('detail',namespace)(uid(11),request,p)
                        self.assertEqual(mismatch['state'],'received')
                        self.assertFalse(mismatch['diagnosis_allowed'])
                        facts[field]=original
                    for overrides in (
                        {'watch_id': uid(12), 'current_watch_id': uid(12)},
                        {'watch_revision': 2, 'current_watch_revision': 2},
                        {'incident_revision': 1, 'current_incident_revision': 1},
                        {'received_at': custody.received_at - timedelta(seconds=1)},
                    ):
                        original = facts.copy()
                        facts.update(overrides)
                        mismatch = await route_function('detail', namespace)(uid(11), request, p)
                        self.assertEqual(mismatch['custody_verification'], 'current')
                        self.assertFalse(mismatch['diagnosis_allowed'])
                        self.assertNotIn('current_opening_acceptance', mismatch)
                        facts.update(original)

    async def test_direct_legacy_update_cannot_relabel_money(self):
        import re
        from types import SimpleNamespace as N
        from bt_contracts_core.errors import PublicError
        from fastapi import HTTPException
        class Tx:
            async def fetchrow(self,sql,*args):
                if 'technical_intake_operations' in sql:
                    return None
                return dict(private_record=json.dumps({'currency':'LBP','fee_minor':5000}),revision=1,author_id=uid(2),order_id=uid(7))
        @asynccontextmanager
        async def transaction(*args,**kwargs):
            yield Tx()
        async def organization(*args):return uid(3)
        async def record_access(*args,**kwargs):return None
        async def receipt_for(*args):return None
        save=route_function('save',dict(organization=organization,require_private_assignment=record_access,
            operation=lambda *args:('operation-1','digest'),re=re,PublicError=PublicError,
            unit_of_work=transaction,receipt_for=receipt_for,json=json,HTTPException=HTTPException,
            lock_case=record_access,require_mutable=record_access))
        with self.assertRaises(PublicError) as error:
            await save(N(currency='USD',order_id=uid(7)),N(headers={'If-Match':'1'},app=N(state=N(pool=None))),N(actor=N(subject_id=uid(2))),uid(9))
        self.assertEqual(error.exception.code,'currency_reissue_required')


class Boundaries(unittest.TestCase):
    def test_published_schemas_and_fixtures_match_models(self):
        for area,module,names in [('maintenance',contract,['Request','Result','Context','Photo','PhotoReceipt','RequestAuthority','AssessmentAccess','AssessmentRequest','AssessmentPhoto','AssessmentQueueAccess','AssessmentQueue','DeliveryHold','DeliveryRetry','DeliveryRecoveryCommand']),
                ('case-lines',lines,['CaseLine','Scope','ScopeReceipt','ScopeAcceptance','RetainedTerms','CurrentScope','CurrentScopeResult']),
                ('intake',current,['OpeningAuthority','CurrentCustodyReceipt','RecordAccess','RecordListAccess','PaidReadiness','OpeningAcceptance','AssessmentCustody'])]:
            for name in names:
                schema=json.loads((ROOT/'packages/contracts-service'/area/(name.lower()+'.schema.v1.json')).read_text())
                self.assertEqual(schema,(AssessmentCustody if name=='AssessmentCustody' else getattr(module,name)).model_json_schema())
        recovery_schema = ROOT / 'packages/contracts-service/intake/intakeoperationcommand.schema.v1.json'
        self.assertEqual(json.loads(recovery_schema.read_text()), IntakeOperationCommand.model_json_schema())
        for area,model in [('maintenance',contract.Result),('case-lines',lines.ScopeReceipt)]:
            fixtures=json.loads((ROOT/'packages/contracts-service'/area/'fixtures.json').read_text())
            self.assertEqual(set(fixtures),{'success','denied','stale','lost_response'})
            for fixture in fixtures.values():
                model.model_validate(fixture)
            if area == 'case-lines':
                self.assertEqual(model.model_validate(fixtures['success']).state, 'accepted')

    def test_maintenance_receipt_revision_matches_state(self):
        fixtures = ROOT / 'packages/contracts-service/maintenance/fixtures.json'
        for fixture in json.loads(fixtures.read_text()).values():
            expected = 1 if fixture['state'] == 'submitted' else 0
            self.assertEqual(contract.Result.model_validate(fixture).revision, expected)
            for invalid in (1 - expected, 2, True, -1):
                with self.subTest(state=fixture['state'], revision=invalid), self.assertRaises(ValidationError):
                    contract.Result.model_validate(fixture | {'revision': invalid})

    def test_accepted_scope_receipt_requires_exact_next_revision(self):
        fixtures = ROOT / 'packages/contracts-service/case-lines/fixtures.json'
        accepted = json.loads(fixtures.read_text())['success']
        for expected in (1, 8):
            bound = accepted | {'expected_revision': expected}
            lines.ScopeReceipt.model_validate(bound | {'revision': expected + 1})
            for revision in (0, expected, expected + 2):
                with self.subTest(expected=expected, revision=revision), self.assertRaises(ValidationError):
                    lines.ScopeReceipt.model_validate(bound | {'revision': revision})

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
        payment.update(currency='USD',state='paid_held',order_kind='job',payment_operation_id=uid(5),payment_revision=1)
        for custody in ('unknown', 1, None, False):
            self.assertFalse(authority.execution_allowed(**(args | {'custody_current':custody}),payment=payment))
        for field in ('payment_operation_id','payment_revision'):
            self.assertFalse(authority.execution_allowed(**args,payment={k:v for k,v in payment.items() if k!=field}))
        for revision in (False, 0, 1.5):
            self.assertFalse(authority.execution_allowed(**args,payment=payment | {'payment_revision':revision}))
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



class EvidenceReplay(unittest.IsolatedAsyncioTestCase):
    async def test_upload_after_receipt_invalidation_only_records_the_attachment(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from starlette.datastructures import QueryParams

        upload = intake_module.load('current_evidence.py:upload')
        evidence = sys.modules[upload.__module__]
        actor, org, order, record, former_receipt = (uid(n) for n in range(2, 7))
        stored = dict(order_id=order, state='received', custody_receipt_id=former_receipt,
                      revision=2, private_record='{"currency":"USD"}')
        writes = []

        class Tx:
            async def fetchrow(self, sql, *args):
                return stored if 'FROM technical_intakes' in sql else None

            async def fetchval(self, sql, *args):
                return 0 if 'count(*)' in sql else None

            async def execute(self, sql, *args):
                writes.append((sql, args))

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Tx()

        async def organization(*args):
            return org

        async def record_access(*args):
            self.assertEqual(args[2:], (org, order, 'write'))

        async def current_custody(*args):
            return False

        req = N(headers={'Idempotency-Key': 'test-evidence-after-custody', 'If-Match': '2'},
                query_params=QueryParams('intake_contract=current'),
                url=N(path='/v1/intake/records/example/evidence'), state=N(request_id='test-evidence'),
                app=N(state=N(pool=None, intake_current_authority=N(current_custody=current_custody))))
        caller = N(actor=N(subject_id=actor))
        body = evidence.EvidenceUpload(kind='condition_photo', media_type='image/png',
                                       content_base64='AAAA', safe_photo_declared=True)
        with patch.multiple(evidence, organization=organization, require_private_assignment=record_access,
                            unit_of_work=transaction), patch.object(evidence, 'bounded_content', return_value=b'test-image'):
            result = await upload(record, body, req, caller)

        self.assertEqual(result.keys(), {'id', 'record_id', 'revision', 'operation_id', 'organization_id'})
        self.assertEqual(result['revision'], 3)
        self.assertEqual([sql.split('(')[0].split()[-1] for sql, _ in writes if sql.startswith('INSERT')], [
            'technical_intake_evidence', 'technical_intake_audit', 'technical_intake_operations',
        ])
        self.assertEqual(len(writes), 5)
        self.assertIn('service-job-assignment', str(writes[0]))
        self.assertEqual(writes[2][1], (record, 3))
        self.assertNotIn('custody_receipt_id', writes[2][0])

    async def test_original_upload_receipts_replay_without_reprocessing(self):
        from hashlib import sha256
        from unittest.mock import patch
        from types import SimpleNamespace as N
        from fastapi import HTTPException
        from bt_contracts_core.errors import PublicError
        from bt_runtime.modules import discover

        intake = discover(ROOT/'services/service-operations/modules/intake')[0]
        route = intake.load('current_evidence.py:upload')
        evidence = sys.modules[route.__module__]
        payload = dict(id=str(uid(10)), record_id=str(uid(9)), revision=2)
        class Assignment:
            async def record_access(self, actor, organization, order, permission):
                return dict(actor_id=actor, organization_id=organization, order_id=order,
                    permission=permission, assignment_revision=1, allowed=tx.allowed)

        req = N(headers={'Idempotency-Key':'test-key-intake','If-Match':'1'},
            url=N(path='/v1/intake/records/example/evidence'),app=N(state=N(pool=None,intake_current_authority=Assignment())))
        caller = N(actor=N(subject_id=uid(2)))

        async def organization(*args):
            return uid(3)

        class Tx:
            async def execute(self, sql, key):
                assert key == f'service-job-assignment:{uid(9)}'

            allowed = True
            prior_digest = None

            async def fetchrow(self, sql, *args):
                if 'FROM technical_intakes' in sql:
                    return dict(order_id=uid(7), revision=2)
                return dict(request_hash=self.prior_digest, result=json.dumps(payload))

        tx = Tx()

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield tx

        with patch.object(evidence,'organization',organization), patch.object(evidence,'unit_of_work',transaction):
            with patch.object(evidence,'bounded_content',side_effect=AssertionError('unexpected reprocessing')):
                for kind, mime in [('prior_owner_record','application/pdf'), ('condition_photo','image/png')]:
                    body=evidence.EvidenceUpload(kind=kind,media_type=mime,content_base64='AAAA')
                    legacy_body=json.dumps(dict(kind=kind,media_type=mime,content_base64='AAAA'),separators=(',',':'))
                    tx.prior_digest=sha256(f'{req.url.path}\n1\n{legacy_body}'.encode()).hexdigest()
                    self.assertEqual(await route(uid(9),body,req,caller), payload | {
                        'operation_id': 'test-key-intake', 'organization_id': str(uid(3))})
                    with self.assertRaises(PublicError) as conflict:
                        await route(uid(9),body.model_copy(update={'content_base64':'BBBB'}),req,caller)
                    self.assertEqual(conflict.exception.code,'idempotency_conflict')
                    tx.allowed=False
                    with self.assertRaises(HTTPException) as denied:
                        await route(uid(9),body,req,caller)
                    self.assertEqual(denied.exception.status_code,404)
                    tx.allowed=True


class CaseAcceptance(unittest.TestCase):
    def test_scope_acceptance_rejects_changed_authority_and_amount(self):
        sys.modules['bt_contracts.service.case_lines.v1'] = lines
        predicate=load('services/service-operations/modules/case-lines/scope.py').current_acceptance
        ids=dict(operation_id=uid(1),actor_id=uid(2),subject_id=uid(2),organization_id=uid(3),
            watch_id=uid(4),request_id=uid(5),quote_id=uid(6))
        binding=lines.ScopeBinding(**ids,request_revision=1,expected_revision=2,
            quote_revision=3,policy_revision=4)
        command=lines.ScopeAcceptance(**binding.model_dump(),accepted_line_ids=[uid(10)],
            total_minor=5000,accepted_terms_revision=5,reviewed_terms=retained_terms())
        scope=lines.Scope(request_id=uid(5),request_revision=1,revision=2,accepted_line_ids=[uid(10)],
            lines=[dict(line_id=uid(10),kind='maintenance.assessment',description='Assessment',
                required=True,amount_minor=5000,assessment_id=uid(11),assessment_revision=1)])
        self.assertTrue(predicate(scope,command,binding=binding,current_terms_revision=5,current_terms=retained_terms()))
        for field in ids:
            changed=lines.ScopeAcceptance.model_validate(command.model_dump()|{field:uid(99)})
            self.assertFalse(predicate(scope,changed,binding=binding,current_terms_revision=5,current_terms=retained_terms()))
        for field in ('quote_revision','policy_revision','total_minor','accepted_terms_revision'):
            changed=lines.ScopeAcceptance.model_validate(command.model_dump()|{field:99})
            self.assertFalse(predicate(scope,changed,binding=binding,current_terms_revision=5,current_terms=retained_terms()))
        with self.assertRaises(ValidationError):
            lines.ScopeAcceptance.model_validate(command.model_dump()|{'accepted_line_ids':[uid(10),uid(10)]})


class CustodyReplacement(unittest.IsolatedAsyncioTestCase):
    async def test_stale_custody_cannot_write_received_or_enqueue_an_event(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from fastapi import HTTPException
        from bt_contracts_core.errors import PublicError

        routes = sys.modules[intake_module.load('current_routes.py:save').__module__]
        actor, org, order, receipt, watch = (uid(n) for n in range(2, 7))
        now = datetime.now(timezone.utc)
        facts = dict(id=receipt, order_id=order, organization_id=org, received_at=now,
            revision=1, valid=True, actor_id=actor, watch_id=watch, current_watch_id=watch,
            watch_revision=1, current_watch_revision=1, incident_revision=0, current_incident_revision=0)
        writes, events = [], []

        async def current_custody(*binding):
            self.assertEqual(binding, (actor, org, order, receipt))
            return current_facts

        class Tx:
            async def fetchrow(self, *args):
                return None

            async def execute(self, sql, *args):
                if 'INSERT' in sql:
                    writes.append(sql)

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Tx()

        async def organization(*args):
            return org

        permissions = []

        async def assigned(p, request, organization_id, order_id, permission):
            self.assertEqual((p.actor.subject_id, organization_id, order_id), (actor, org, order))
            permissions.append(permission)
            if permission == 'assess' and not assessor:
                raise HTTPException(403)

        async def enqueue(tx, event, destinations):
            events.append(event)

        req = N(headers={'Idempotency-Key':'test-current-custody'}, url=N(path='/v1/intake/records'),
            state=N(request_id='test-custody'), app=N(state=N(pool=None,
                intake_current_authority=N(current_custody=current_custody))))
        caller = N(actor=N(subject_id=actor))
        body = routes.Intake(order_id=order, custody_receipt_id=receipt, serial='Private serial',
            reference='Watch reference', movement='Mechanical', received_condition='Worn',
            accessories='', reported_issue='Stopped', assessed_issue='', diagnostic_opening_permission=False,
            no_polish_acknowledged=False, fee_acknowledged=False, fee_minor=0, currency='USD')

        with patch.multiple(routes, unit_of_work=transaction, organization=organization,
                            record_access=assigned, enqueue=enqueue):
            for current_facts in (facts | {'current_watch_revision':2},
                                  facts | {'current_incident_revision':1},
                                  facts | {'received_at':now + timedelta(hours=1)},
                                  facts | {'actor_id':uid(99)}, False):
                with self.assertRaises(PublicError):
                    await routes.save(body, req, caller)
            current_facts = {key: facts[key] for key in routes.CurrentCustodyReceipt.__base__.model_fields}
            with self.assertRaises(HTTPException) as unavailable:
                await routes.save(body, req, caller)
            self.assertEqual(unavailable.exception.status_code, 503)
            self.assertFalse(writes)
            self.assertFalse(events)

            current_facts = facts
            acceptance = dict(quote_id=uid(11), quote_revision=2, accepted_terms_revision=3,
                              consent_revision=4)
            customer_facts = dict(
                **acceptance, actor_id=actor, organization_id=org, order_id=order,
                receipt_id=receipt, receipt_revision=1, received_at=now, watch_id=watch,
                watch_revision=1, incident_revision=0, current_watch_id=watch,
                current_watch_revision=1, current_incident_revision=0, current=True,
                assigned=True, permission=True, customer_opening_permission=True,
                accepted_assessment_fee=True, customer_no_polish_acknowledged=True,
                accepted_fee_minor=2500, currency='USD',
            )

            async def current_opening_facts(*binding):
                self.assertEqual(binding, (actor, org, order))
                return customer_facts

            req.app.state.intake_current_authority.current = current_opening_facts
            reviewed = body.model_copy(update={
                'diagnostic_opening_permission': True, 'no_polish_acknowledged': True,
                'fee_acknowledged': True, 'fee_minor': 2500,
                'opening_acceptance': OpeningAcceptance(**acceptance),
            })
            rejected = [
                reviewed.model_copy(update={'custody_receipt_id': None}),
                reviewed.model_copy(update={'opening_acceptance': None}),
                reviewed.model_copy(update={'fee_minor': 2501}),
                reviewed.model_copy(update={'fee_acknowledged': False}),
                *(reviewed.model_copy(update={'opening_acceptance': OpeningAcceptance(
                    **(acceptance | {field: value}))})
                  for field, value in [('quote_id', uid(99)), ('quote_revision', 1),
                                       ('accepted_terms_revision', 2), ('consent_revision', 3)]),
            ]
            for command in rejected:
                with self.assertRaises(PublicError) as mismatch:
                    await routes.save(command, req, caller)
                self.assertEqual(mismatch.exception.code, 'opening_acceptance_unconfirmed')
            customer_facts['accepted_assessment_fee'] = False
            with self.assertRaises(PublicError):
                await routes.save(reviewed, req, caller)
            self.assertFalse(writes)
            self.assertFalse(events)
            customer_facts['accepted_assessment_fee'] = True
            result = await routes.save(reviewed, req, caller)
            self.assertEqual(result['state'], 'received')
            self.assertTrue(result['diagnosis_allowed'])
            self.assertEqual(len(events), 1)
            writes.clear()
            events.clear()

            assessor = False
            assessment = body.model_copy(update={'assessed_issue': 'Examined movement'})
            reviewed_custody = routes.AssessmentCustody(watch_id=watch, watch_revision=1,
                receipt_id=receipt, receipt_revision=1, incident_revision=0)
            bound_assessment = assessment.model_copy(update={'reviewed_assessment_custody': reviewed_custody})
            with self.assertRaises(PublicError) as no_custody:
                await routes.save(assessment.model_copy(update={'custody_receipt_id': None}), req, caller)
            self.assertEqual(no_custody.exception.code, 'assessment_requires_custody')
            with self.assertRaises(HTTPException) as denied:
                await routes.save(bound_assessment, req, caller)
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(permissions[-2:], ['write', 'assess'])
            self.assertFalse(writes)
            self.assertFalse(events)

            assessor = True
            for changed in (
                {'revision': 2},
                {'watch_revision': 2, 'current_watch_revision': 2},
                {'incident_revision': 1, 'current_incident_revision': 1},
            ):
                current_facts = facts | changed
                with self.assertRaises(PublicError) as stale:
                    await routes.save(bound_assessment, req, caller)
                self.assertEqual(stale.exception.code, 'stale_assessment_custody')
            current_facts = facts
            with self.assertRaises(PublicError) as missing:
                await routes.save(assessment, req, caller)
            self.assertEqual(missing.exception.code, 'stale_assessment_custody')
            self.assertFalse(writes)
            self.assertFalse(events)
            result = await routes.save(bound_assessment, req, caller)
            self.assertEqual(result['state'], 'received')
            self.assertFalse(result['diagnosis_allowed'])
            self.assertEqual(len(events), 1)

    async def test_newer_verified_receipt_supersedes_but_retains_history(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from bt_contracts_core.errors import PublicError
        from bt_runtime.modules import discover

        intake = discover(ROOT/'services/service-operations/modules/intake')[0]
        routes = sys.modules[intake.load('current_routes.py:save').__module__]
        original_at = datetime(2026, 11, 16, tzinfo=timezone.utc)
        row = dict(order_id=uid(7), custody_receipt_id=uid(8), custody_revision=2,
            received_at=original_at, revision=4, state='received', private_record='{"currency":"USD","assessed_issue":"Existing finding"}')
        former_binding = dict(watch_id=str(uid(11)), watch_revision=1, receipt_id=str(uid(8)),
                              receipt_revision=2, incident_revision=0)
        row['private_record'] = json.dumps(json.loads(row['private_record']) |
                                           {'assessment_custody': former_binding})
        writes = []

        class Tx:
            async def fetchrow(self, sql, *args):
                return row if 'FROM technical_intakes' in sql else None

            async def fetchval(self, sql, *args):
                return False

            async def execute(self, sql, *args):
                if not sql.startswith('SELECT'):
                    writes.append((sql, args))

        @asynccontextmanager
        async def transaction(*args, **kwargs):
            yield Tx()

        async def organization(*args):
            return uid(3)

        async def verify_access(*args):
            from fastapi import HTTPException
            if args[-1] == 'assess':
                raise HTTPException(403)

        async def verify(body, org, req, actor):
            return receipt

        async def enqueue(*args):
            pass

        req = N(headers={'If-Match':'4','Idempotency-Key':'test-key-custody'},
            url=N(path='/v1/intake/records/example'),app=N(state=N(pool=None)),
            state=N(request_id='test-request'))
        caller = N(actor=N(subject_id=uid(2)))
        body = routes.Intake(order_id=uid(7),custody_receipt_id=uid(10),
            serial='Private serial',reference='Watch reference',movement='Mechanical',
            received_condition='Worn',accessories='',reported_issue='Stopped',assessed_issue='Existing finding',
            diagnostic_opening_permission=False,no_polish_acknowledged=False,
            fee_acknowledged=False,fee_minor=0,currency='USD')

        with patch.multiple(routes, unit_of_work=transaction, organization=organization,
                receipt_for=verify, enqueue=enqueue, record_access=verify_access,
                require_private_assignment=verify_access):
            for receipt in (None, N(id=uid(10), revision=2), N(id=uid(10), revision=1)):
                with self.assertRaises(PublicError) as error:
                    await routes.save(body, req, caller, uid(9))
                self.assertEqual(error.exception.code,'immutable_custody')
            self.assertEqual(writes, [])
            receipt = N(id=uid(8), revision=3, received_at=original_at, order_id=uid(7), organization_id=uid(3),
                        watch_id=uid(11), watch_revision=1, incident_revision=0)
            with self.assertRaises(PublicError) as stale:
                await routes.save(body.model_copy(update={
                    'custody_receipt_id': uid(8), 'assessed_issue': 'Edited on earlier custody',
                    'reviewed_assessment_custody': AssessmentCustody.model_validate(former_binding),
                }), req, caller, uid(9))
            self.assertEqual(stale.exception.code, 'stale_assessment_custody')
            self.assertEqual(writes, [])
            same_receipt = body.model_copy(update={'custody_receipt_id': uid(8)})
            for reviewed in (None, AssessmentCustody.model_validate(former_binding)):
                with self.assertRaises(PublicError) as stale_receipt:
                    await routes.save(same_receipt.model_copy(update={
                        'reviewed_receipt_revision': reviewed,
                    }), req, caller, uid(9))
                self.assertEqual(stale_receipt.exception.code, 'stale_receipt_revision')
                self.assertEqual(writes, [])
            current_binding = routes.assessment_custody(receipt)
            advanced = await routes.save(same_receipt.model_copy(update={
                'reviewed_receipt_revision': AssessmentCustody.model_validate(current_binding),
            }), req, caller, uid(9))
            self.assertEqual(advanced['revision'], 5)
            self.assertFalse(advanced['diagnosis_allowed'])
            advanced_private = json.loads(writes[0][1][7])
            self.assertEqual(advanced_private['custody_history'][0]['receipt_revision'], 2)
            self.assertEqual(advanced_private['assessed_issue'], '')
            self.assertNotIn('reviewed_receipt_revision', advanced_private)
            writes.clear()
            receipt = N(id=uid(10),revision=3,received_at=original_at+timedelta(hours=1),
                        order_id=uid(7), organization_id=uid(3), watch_id=uid(12), watch_revision=1, incident_revision=0)
            from fastapi import HTTPException
            from_review = routes.AssessmentCustody.model_validate(routes.assessment_custody(receipt))
            with self.assertRaises(HTTPException) as denied:
                await routes.save(body.model_copy(update={'assessed_issue': 'Replaced finding',
                    'reviewed_assessment_custody': from_review}), req, caller, uid(9))
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(writes, [])
            for review in (None, from_review.model_copy(update={'incident_revision': 1}),
                           from_review.model_copy(update={'watch_revision': 2}),
                           from_review.model_copy(update={'receipt_revision': 4}),
                           from_review.model_copy(update={'receipt_id': uid(8)})):
                with self.assertRaises(PublicError) as stale:
                    await routes.save(body.model_copy(update={'reviewed_receipt_revision': review}), req, caller, uid(9))
                self.assertEqual(stale.exception.code, 'stale_receipt_revision')
                self.assertEqual(writes, [])
            result = await routes.save(body.model_copy(update={'reviewed_receipt_revision': from_review}),
                                       req, caller, uid(9))

        self.assertEqual(result['revision'], 5)
        self.assertFalse(result['diagnosis_allowed'])
        _, updated = writes[0]
        self.assertEqual(updated[4:7], (receipt.id,receipt.revision,receipt.received_at))
        private = json.loads(updated[7])
        self.assertEqual(private['assessed_issue'], '')
        self.assertEqual(private['assessment_history'], [{
            'finding': 'Existing finding', 'custody': former_binding, 'intake_revision': 4,
        }])
        self.assertEqual(private['custody_history'], [{
            'receipt_id':str(uid(8)),'receipt_revision':2,'intake_revision':4,
            'received_at':original_at.isoformat(),
        }])
        self.assertNotIn('custody_history',routes.present(row | {'private_record':updated[7]})['private_record'])


class AssessmentDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_operation_recovery_requires_an_explicit_authority_decision(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from fastapi import HTTPException
        from bt_runtime.modules import Module

        module = Module('L17.maintenance-requests',
            ROOT / 'services/service-operations/modules/maintenance-requests',
            (), (), None, {}, {}, ())
        lookup = module.load('routes.py:operation')
        close = module.load('routes.py:close_operation')
        routes = sys.modules[lookup.__module__]
        actor, org, key = uid(2), uid(3), uid(1)
        accesses = []
        mutations = []

        async def check(*binding):
            accesses.append(binding)
            if isinstance(decision, Exception):
                raise decision
            return decision

        class Store:
            async def fetchrow(store, sql, *args):
                self.assertEqual(args, (key, actor, org))
                return None

            async def execute(store, sql, *args):
                mutations.append(args)

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertEqual(lock_key, f'maintenance:{key}')
            yield Store()

        state = N(pool=None)
        req = N(app=N(state=state))
        with patch.object(routes, 'unit_of_work', transaction):
            for resolve in (lookup, close):
                for decision, status in [(None, 503), (1, 503), ('true', 503),
                                         ({'allowed': False}, 503), (TimeoutError(), 503),
                                         (ValueError(), 503), (False, 403)]:
                    state.maintenance_provider = N(operation_access=check)
                    with self.assertRaises(HTTPException) as failure:
                        await resolve(key, org, req, actor)
                    self.assertEqual(failure.exception.status_code, status)
                state.maintenance_provider = N()
                with self.assertRaises(HTTPException) as missing:
                    await resolve(key, org, req, actor)
                self.assertEqual(missing.exception.status_code, 503)
            self.assertEqual(mutations, [])
            state.maintenance_provider = N(operation_access=check)
            decision = True
            self.assertEqual(await close(key, org, req, actor),
                             {'closed': True, 'operation_id': key, 'organization_id': org})
        self.assertEqual(accesses, [(actor, org, key)] * 15)
        self.assertEqual(mutations, [(key, actor, org)] * 2)

    async def test_assigned_business_can_read_report_and_photo_until_revoked(self):
        from types import SimpleNamespace as N
        from fastapi import HTTPException
        from bt_runtime.modules import Module

        module = Module('L17.maintenance-requests',
            ROOT / 'services/service-operations/modules/maintenance-requests',
            (), (), None, {}, {}, ())
        assessment = module.load('routes.py:assessment')
        photo = module.load('routes.py:assessment_photo')
        buyer, org, staff, request_id, photo_ref = (uid(n) for n in (2, 3, 6, 7, 8))
        saved = request(photo_refs=[photo_ref], known_modifications='Private modification')
        now = datetime(2026, 11, 16, tzinfo=timezone.utc)

        class Store:
            @asynccontextmanager
            async def acquire(self, *, timeout):
                yield self

            @asynccontextmanager
            async def transaction(self, *, isolation):
                yield self

            async def execute(self, sql, key):
                assert key.startswith('maintenance-staff:')

            downloads = 0
            request_reads = 0

            async def fetchrow(self, sql, *binding):
                if 'FROM maintenance_requests' in sql:
                    self.request_reads += 1
                if binding == (request_id, org):
                    return dict(private_request=saved.model_dump_json(), revision=1, submitted_at=now)
                if binding == (photo_ref, request_id, saved.operation_id, org, buyer, saved.watch_id):
                    self.downloads += 1
                    return dict(media_type='image/png', content=b'test-image')

        class Provider:
            allowed = True
            assignment_revision = 1
            request_revision = 1

            async def assessment_access(self, actor, organization, requested):
                return dict(actor_id=actor, organization_id=organization, request_id=requested,
                    watch_id=saved.watch_id, brand_id=saved.brand_id, intervention=saved.intervention,
                    request_revision=self.request_revision, assignment_revision=self.assignment_revision,
                    capability_revision=1, allowed=self.allowed and actor == staff
                    and organization == org and requested == request_id)

        provider = Provider()
        pool = Store()
        req = N(app=N(state=N(pool=pool, maintenance_provider=provider)))
        report = await assessment(request_id, org, req, staff)
        self.assertEqual(report.reported_symptoms, saved.reported_symptoms)
        self.assertEqual(report.known_modifications, saved.known_modifications)
        self.assertEqual(report.photo_refs, [photo_ref])
        self.assertTrue(report.limited_assessment_permission)
        self.assertEqual(report.intervention, saved.intervention)
        self.assertEqual((report.assessor_id, report.assignment_revision), (staff, 1))
        self.assertNotIn('actor_id', report.model_dump())
        self.assertEqual((await photo(request_id, photo_ref, org, req, staff)).photo_ref, photo_ref)

        for operation, args, status in [
            (assessment, (request_id, uid(99), req, staff), 404),
            (assessment, (request_id, org, req, buyer), 404),
            (assessment, (uid(99), org, req, buyer), 404),
            (photo, (request_id, uid(99), org, req, staff), 404),
        ]:
            with self.assertRaises(HTTPException) as failure:
                await operation(*args)
            self.assertEqual(failure.exception.status_code, status)

        provider.request_revision = 2
        with self.assertRaises(HTTPException) as stale:
            await assessment(request_id, org, req, staff)
        self.assertEqual(stale.exception.status_code, 404)
        provider.request_revision = 1

        provider.allowed = False
        with self.assertRaises(HTTPException) as denied:
            await photo(request_id, photo_ref, org, req, staff)
        self.assertEqual(denied.exception.status_code, 404)
        async def authority_failure(*args):
            if isinstance(decision, Exception):
                raise decision
            return decision

        provider.assessment_access = authority_failure
        for decision, status in (
            (False, 404), (HTTPException(403), 404), (HTTPException(404), 404),
            (HTTPException(401), 401), (HTTPException(503), 503), (HTTPException(502), 503),
            (None, 503), ({'allowed': True}, 503), (TimeoutError(), 503),
        ):
            prior_reads = pool.request_reads
            for target in (request_id, uid(99)):
                for read, args in (
                    (assessment, (target, org, req, staff)),
                    (photo, (target, photo_ref, org, req, staff)),
                ):
                    with self.subTest(decision=decision, read=read.__name__), self.assertRaises(HTTPException) as failure:
                        await read(*args)
                    self.assertEqual(failure.exception.status_code, status)
            self.assertEqual(pool.request_reads, prior_reads)
        self.assertEqual(pool.downloads, 1)

    async def test_upload_checks_exact_current_assessment_before_storing_private_bytes(self):
        from base64 import b64encode
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from bt_contracts_core.errors import PublicError

        upload = maintenance_module.load('routes.py:photo')
        routes = sys.modules[upload.__module__]
        actor, org, watch, brand, key, upload_key = (uid(n) for n in range(1, 7))
        body = contract.Photo(
            operation_id=upload_key, request_operation_id=key, organization_id=org,
            watch_id=watch, brand_id=brand, intervention='overhaul_assessment',
            watch_revision=1, capability_revision=2, policy_revision=3,
            media_type='image/png', safe_photo_declared=True,
            content_base64=b64encode(b'\x89PNG\r\n\x1a\n').decode('ascii'))
        destination = dict(organization_id=org, brand_id=brand, display_name='Synthetic business',
                           capability_revision=2, policy_revision=3, interventions=['overhaul_assessment'])
        current = dict(actor_id=actor, subject_id=actor, watch_id=watch, watch_revision=1,
                       destinations=[destination])
        req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            pool=None, maintenance_provider=SimpleNamespace(context=AsyncMock(side_effect=lambda *_: current)))))
        store = AsyncMock(return_value=uid(99))
        tx = object()

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertEqual(lock_key, f'maintenance:{key}')
            yield tx

        with patch.multiple(routes, unit_of_work=transaction, store_photo=store):
            for field, value, code in (
                ('brand_id', uid(98), 'destination_ineligible'),
                ('interventions', ['limited_maintenance'], 'destination_ineligible'),
                ('capability_revision', 4, 'stale_photo_scope'),
                ('policy_revision', 4, 'stale_photo_scope'),
            ):
                current['destinations'] = [destination | {field: value}]
                with self.assertRaises(PublicError) as failure:
                    await upload(body, req, actor)
                self.assertEqual(failure.exception.code, code)
            current.update(destinations=[destination], watch_revision=2)
            with self.assertRaises(PublicError) as stale:
                await upload(body, req, actor)
            self.assertEqual(stale.exception.code, 'stale_photo_scope')
            store.assert_not_awaited()
            current['watch_revision'] = 1
            receipt = await upload(body, req, actor)
            self.assertEqual(receipt.model_dump(), {
                **body.model_dump(include=set(contract.PhotoBinding.model_fields)),
                'photo_ref': uid(99), 'actor_id': actor, 'subject_id': actor, 'revision': 1,
            })
            store.assert_awaited_once_with(tx, actor, body, b'\x89PNG\r\n\x1a\n')

    async def test_queue_withholds_references_without_current_business_assignment(self):
        from types import SimpleNamespace
        from fastapi import HTTPException

        queue = maintenance_module.load('routes.py:assessment_inbox')
        actor, business = uid(2), uid(3)
        decisions = (
            (False, 403),
            (None, 503),
            ({'actor_id': actor, 'organization_id': uid(99),
              'assignment_revision': 1, 'request_ids': [uid(10)]}, 403),
            ({'actor_id': actor, 'organization_id': business,
              'assignment_revision': True, 'request_ids': [uid(10)]}, 503),
        )

        async def check(requested_actor, organization):
            self.assertEqual((requested_actor, organization), (actor, business))
            return decision

        # No database access is available before a valid assignment decision.
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            maintenance_provider=SimpleNamespace(assessment_queue_access=check))))
        for decision, status in decisions:
            with self.subTest(status=status), self.assertRaises(HTTPException) as error:
                await queue(business, request, actor_id=actor)
            self.assertEqual(error.exception.status_code, status)

    def test_unsubmitted_photo_retention_uses_original_instant(self):
        uploaded = datetime(2026, 11, 16, tzinfo=timezone.utc)
        expiry = uploaded + timedelta(days=7)
        self.assertEqual(contract.unsubmitted_photo_expires_at(uploaded), expiry)
        for offset, expected in [(-1, True), (0, False), (1, False)]:
            self.assertEqual(contract.unsubmitted_photo_is_current(
                uploaded, expiry + timedelta(microseconds=offset)), expected)
        self.assertFalse(contract.unsubmitted_photo_is_current(uploaded, uploaded - timedelta(seconds=1)))
        with self.assertRaises(ValueError):
            contract.unsubmitted_photo_expires_at(uploaded.replace(tzinfo=None))


class DurableScope(unittest.IsolatedAsyncioTestCase):
    async def test_current_acceptance_retry_lookup_and_revocation(self):
        from types import SimpleNamespace as N
        from unittest.mock import patch
        from fastapi import HTTPException
        from bt_runtime.modules import Module

        sys.modules['bt_contracts.service.case_lines.v1'] = lines
        module = Module('L17.case-lines', ROOT / 'services/service-operations/modules/case-lines',
            (), (), None, {}, {}, ())
        accept = module.load('routes.py:accept')
        routes = sys.modules[accept.__module__]
        actor, org, watch, request_id, quote_id, line_id, operation, case, assessment = (uid(n) for n in range(1, 10))
        buyer = N(actor=N(subject_id=actor, organization_id=None))
        body = routes.Acceptance(operation_id=operation, case_id=case, request_id=request_id,
            actor_id=actor, organization_id=org, watch_id=watch, request_revision=1,
            expected_revision=0, quote_id=quote_id, quote_revision=1, policy_revision=1,
            assessment_id=assessment, assessment_revision=1)
        line = dict(id=str(line_id), kind='labor', label='Repair', amount_minor=5000, mandatory=True)
        decision = dict(selected_line_ids=[str(line_id)], terms_digest='a'*64, amounts={'assessment_fee_minor':0,'payable_minor':5000})
        quote = dict(id=str(quote_id), terms_digest='a'*64, currency='USD', state='accepted', policy={'revision':1}, source_id=str(case),
                     source_revision=1, diagnosis='Measured finding', assessment_id=str(assessment), assessment_revision=1,
                     revision=1, organization_id=str(org), buyer_id=str(actor),
                     lines=[line], assessment_fee_minor=0, decision=decision | {'actor_id':str(actor),'state':'accepted'})
        diagnosis = dict(request_id=request_id, organization_id=org, watch_id=watch, assessment_id=assessment,
                         revision=1, body={'diagnosis':'Measured finding','lines':[line | {'amount_minor':None}]})
        evidence = {}
        events = []

        class Store:
            async def fetchrow(self, sql, *args):
                if 'WHERE operation_id=$1' in sql:
                    return evidence.get(args[0])
                if 'SELECT * FROM service_case_scopes WHERE case_id=$1' in sql:
                    self_test.assertEqual(args, (case,))
                    return dict(organization_id=org, buyer_id=actor, body={'case_id':str(case)})
                return None

            async def fetchval(self, sql, *args):
                if 'to_regclass' in sql:
                    return False
                if 'service_case_scopes' in sql:
                    return 0
                self_test.assertEqual(args, (request_id, actor, org, watch))
                return 1

            async def execute(self, sql, *args):
                if 'INSERT INTO service_case_scope_operations' in sql:
                    key, _, command, receipt = args
                    evidence[key] = {'command':command, 'receipt':receipt}
                if 'INSERT INTO service_case_scope_outbox' in sql:
                    events.append(args)

            @asynccontextmanager
            async def acquire(self):
                yield self

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertIn(lock_key, (f'service-job-assignment:{case}', f'service-job-assignment:{request_id}'))
            yield pool

        from unittest.mock import AsyncMock
        self_test = self
        req = N(app=N(state=N(pool=Store())))
        source = AsyncMock()
        pricing = AsyncMock(return_value=quote)
        with patch.multiple(routes, unit_of_work=transaction, read=pricing,
                current_source=source, acknowledged_diagnosis=AsyncMock(return_value=diagnosis)):
            for field, value in [('case_id', request_id), ('expected_revision', 1), ('request_revision', 2)]:
                with self.assertRaises(HTTPException) as stale:
                    await accept(request_id, body.model_copy(update={field: value}), req, buyer)
                self.assertEqual(stale.exception.status_code, 409)
            self.assertFalse(events)
            receipt = await accept(request_id, body, req, buyer)
            self.assertEqual((receipt['case_id'], receipt['request_id'], receipt['revision']), (str(case), str(request_id), 1))
            self.assertEqual(pricing.await_args.args[2], f'/v1/repair-quotes/{quote_id}')
            self.assertEqual(events, [(operation, case, 1)])
            pricing.side_effect = ConnectionError('unavailable')
            req.app.state.pool = Store()
            self.assertEqual(await accept(request_id, body, req, buyer), receipt)
            self.assertEqual(await routes.lookup(operation, req, buyer), receipt)
            with self.assertRaises(HTTPException) as wrong_org:
                await routes.lookup(operation, req, buyer, organization_id=uid(99))
            self.assertEqual(wrong_org.exception.status_code, 404)
            with self.assertRaises(HTTPException) as other_buyer:
                await accept(request_id, body, req, N(actor=N(subject_id=uid(99), organization_id=None)))
            self.assertEqual(other_buyer.exception.status_code, 403)
            self.assertEqual(len(events), 1)


if __name__ == '__main__':
    unittest.main()
