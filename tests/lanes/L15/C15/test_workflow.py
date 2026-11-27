import asyncio
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('changes_workflow', ROOT / 'services/catalog/modules/job-changes/workflow.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
FIXTURE = json.loads((ROOT / 'packages/contracts-catalog/job-changes/fixtures.json').read_text())


class Provider:
    def __init__(self):
        self.allowed = True
        self.fresh = True
        self.lost = None
        self.lost_before = False
        self.receipts = {}
        self.calls = []
        self.mismatch = False
        self.expiry = '2026-11-17T10:00:01Z'
        self.now = '2026-11-17T10:00:00Z'

    async def authorized(self, change, actor, organization, timeout_seconds):
        return self.allowed

    async def current(self, change, approval, timeout_seconds):
        return self.fresh and (approval is None or module.contract.instant(self.now) < module.contract.instant(self.expiry))

    async def hold(self, change, timeout_seconds):
        return await self.receipt(change, None, 'held')

    async def resume(self, change, approval, timeout_seconds):
        return await self.receipt(change, approval, 'reapproved')

    async def receipt(self, change, approval, state):
        self.calls.append((change.operation_id, state))
        key = (change.operation_id, state)
        if self.lost_before and self.lost == state:
            raise TimeoutError()
        self.receipts.setdefault(key, {**asdict(change), 'state': state, 'approval': asdict(approval) if approval else None})
        if self.lost == state:
            raise TimeoutError()
        receipt = dict(self.receipts[key])
        if self.mismatch:
            receipt['watch_id'] = 'different-watch'
        return receipt


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name) / 'changes.db')
        self.provider = Provider()
        self.change = module.Change(**FIXTURE['change'])
        self.approval = module.Approval(**FIXTURE['approval'])
        self.store = module.Workflow(self.path, self.provider, lambda: self.provider.now)

    def tearDown(self):
        self.store.db.close()
        self.folder.cleanup()

    async def start(self):
        return await self.store.start(self.change, 'buyer-1', 'brand-1')

    async def accept(self):
        return await self.store.accept('change-1', self.approval, 'buyer-1', 'brand-1')

    async def test_complete_hold_then_fresh_acceptance(self):
        held = await self.start()
        self.assertEqual(held['state'], 'awaiting_reapproval')
        self.assertEqual(held['active_scope_id'], 'scope-5')
        self.assertIn('eligibility', held['invalidated'])
        self.assertFalse(held['execution_authority'])
        done = await self.accept()
        self.assertEqual(done, FIXTURE['responses']['success'])
        self.assertEqual(self.provider.calls, [('change-1', 'held'), ('change-1', 'reapproved')])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM l15_change_outbox').fetchone()[0], 4)
        self.assertEqual(json.loads(self.store.db.execute('SELECT intent FROM l15_changes').fetchone()[0])['source_scope_id'], 'scope-4')

    async def test_lost_hold_response_survives_restart_and_same_retry(self):
        self.provider.lost = 'held'
        pending = await self.start()
        self.assertEqual(pending, FIXTURE['responses']['lost_hold_response'])
        self.assertEqual(pending['active_scope_id'], 'scope-4')
        with self.assertRaisesRegex(module.Rejected, 'hold_required'):
            await self.accept()
        self.store.db.close()
        self.store = module.Workflow(self.path, self.provider, lambda: self.provider.now)
        self.provider.lost = None
        self.assertEqual((await self.store.resume('change-1', 'buyer-1', 'brand-1'))['state'], 'awaiting_reapproval')
        self.assertEqual(len(self.provider.receipts), 1)

    async def test_lost_resume_response_is_stable_after_restart(self):
        await self.start()
        self.provider.lost = 'reapproved'
        self.assertEqual((await self.accept())['state'], 'pending_resume')
        self.store.db.close()
        self.store = module.Workflow(self.path, self.provider, lambda: self.provider.now)
        self.provider.lost = None
        self.assertEqual((await self.accept())['state'], 'reapproved')
        self.assertEqual(len(self.provider.receipts), 2)

    async def test_stale_pending_acceptance_requires_terminal_fence_before_replacement(self):
        await self.start()
        self.provider.lost_before = True
        self.provider.lost = 'reapproved'
        await self.accept()
        self.provider.fresh = False
        calls = []

        async def reconcile(change, approval, operation_revision, timeout_seconds):
            calls.append(operation_revision)
            return {**asdict(change), 'state': 'unknown',
                    'approval': asdict(approval), 'operation_revision': operation_revision}
        self.provider.reconcile = reconcile
        pending = await self.store.resume('change-1', 'buyer-1', 'brand-1')
        self.assertEqual(pending['state'], 'pending_resume')
        replacement = replace(self.approval, quote_revision=2, acceptance_revision=2)
        with self.assertRaisesRegex(module.Rejected, 'conflict'):
            await self.store.accept('change-1', replacement, 'buyer-1', 'brand-1')

        async def fenced(change, approval, operation_revision, timeout_seconds):
            return {**asdict(change), 'state': 'not_applied',
                    'approval': asdict(approval), 'operation_revision': operation_revision}
        self.provider.reconcile = fenced
        recovered = await self.store.resume('change-1', 'buyer-1', 'brand-1')
        self.assertEqual(recovered['state'], 'awaiting_reapproval')
        self.assertEqual(recovered['revision'], pending['revision'] + 1)
        self.assertEqual(calls, [3])
        self.store.db.close()
        self.store = module.Workflow(self.path, self.provider, lambda: self.provider.now)
        self.assertIsNone(self.store.load('change-1')[2])
        self.provider.fresh = True
        self.provider.lost = None
        self.assertNotIn(('change-1', 'reapproved'), self.provider.receipts)
        done = await self.store.accept('change-1', replacement, 'buyer-1', 'brand-1')
        self.assertEqual(done['state'], 'reapproved')
        self.assertEqual(self.store.load('change-1')[2]['quote_revision'], 2)

    async def test_recovery_timeout_or_wrong_revision_keeps_original_acceptance(self):
        await self.start()
        self.provider.lost = 'reapproved'
        await self.accept()
        self.provider.fresh = False

        async def timeout(*args, **kwargs):
            raise TimeoutError()
        self.provider.reconcile = timeout
        self.assertEqual((await self.store.resume('change-1', 'buyer-1', 'brand-1'))['state'], 'pending_resume')

        async def wrong_revision(change, approval, operation_revision, timeout_seconds):
            return {**asdict(change), 'state': 'not_applied',
                    'approval': asdict(approval), 'operation_revision': operation_revision - 1}
        self.provider.reconcile = wrong_revision
        self.assertEqual((await self.store.resume('change-1', 'buyer-1', 'brand-1'))['state'], 'pending_resume')
        self.assertEqual(self.store.load('change-1')[2], asdict(self.approval))

    async def test_duplicate_and_conflicting_intent(self):
        result = await self.start()
        self.assertEqual(await self.start(), result)
        with self.assertRaisesRegex(module.Rejected, 'conflict'):
            await self.store.start(replace(self.change, reason='Another reason'), 'buyer-1', 'brand-1')
        with self.assertRaisesRegex(module.Rejected, 'change_exists'):
            await self.store.start(replace(self.change, operation_id='change-2'), 'buyer-1', 'brand-1')

    async def test_wrong_business_and_revocation_hide_private_read(self):
        await self.start()
        for actor, organization in [('buyer-2', 'brand-1'), ('buyer-1', 'brand-2')]:
            with self.assertRaisesRegex(module.Rejected, 'denied'):
                await self.store.lookup('change-1', actor, organization)
        self.provider.allowed = False
        with self.assertRaisesRegex(module.Rejected, 'denied'):
            await self.store.lookup('change-1', 'buyer-1', 'brand-1')

    async def test_stale_initial_revision_and_old_proof(self):
        self.provider.fresh = False
        with self.assertRaisesRegex(module.Rejected, 'stale_revision'):
            await self.start()
        self.provider.fresh = True
        await self.start()
        with self.assertRaisesRegex(module.Rejected, 'stale_scope'):
            await self.store.accept('change-1', replace(self.approval, scope_id='scope-4'), 'buyer-1', 'brand-1')
        self.provider.fresh = False
        with self.assertRaisesRegex(module.Rejected, 'stale_prerequisites'):
            await self.accept()

    async def test_before_equal_after_grant_boundary(self):
        await self.start()
        for now in ['2026-11-17T10:00:01Z', '2026-11-17T10:00:02Z']:
            self.provider.now = now
            with self.assertRaisesRegex(module.Rejected, 'stale_prerequisites'):
                await self.accept()
        self.provider.now = '2026-11-17T10:00:00Z'
        self.assertEqual((await self.accept())['state'], 'reapproved')

    async def test_conflicting_receipt_keeps_hold_pending(self):
        self.provider.mismatch = True
        self.assertEqual((await self.start())['state'], 'pending_hold')

    async def test_revocation_after_hold_never_activates_scope(self):
        original = self.provider.hold
        async def revoke(*args, **kwargs):
            receipt = await original(*args, **kwargs)
            self.provider.allowed = False
            return receipt
        self.provider.hold = revoke
        with self.assertRaisesRegex(module.Rejected, 'denied'):
            await self.start()
        self.assertEqual(self.store.load('change-1')[1]['state'], 'pending_hold')

    async def test_conflicting_acceptance_is_rejected(self):
        await self.start()
        await self.accept()
        with self.assertRaisesRegex(module.Rejected, 'conflict'):
            await self.store.accept('change-1', replace(self.approval, quote_revision=2), 'buyer-1', 'brand-1')

    def test_money_revisions_and_independence(self):
        for updates in [{'total_minor': True}, {'currency': 'EUR'}, {'business_fee_minor': 50000},
                        {'quote_revision': False}, {'approver_id': 'person-1'}, {'accepted_at': '2026-11-17T10:00:00+02:00'}]:
            with self.assertRaises(module.Rejected):
                replace(self.approval, **updates)
        for updates in [{'reason': 'x' * 1001}, {'expected_revision': 0}, {'operation_id': '../private'}]:
            with self.assertRaises(module.Rejected):
                replace(self.change, **updates)

    async def test_outbox_is_atomic_with_transition(self):
        self.provider.lost = 'held'
        await self.start()
        self.provider.lost = None
        self.store.db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON l15_change_outbox BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        with self.assertRaises(Exception):
            await self.store.resume('change-1', 'buyer-1', 'brand-1')
        self.assertEqual(self.store.load('change-1')[1]['state'], 'pending_hold')

    async def test_concurrent_identical_start_and_accept(self):
        original = self.provider.current
        async def yielded(*args, **kwargs):
            await asyncio.sleep(0)
            return await original(*args, **kwargs)
        self.provider.current = yielded
        starts = await asyncio.gather(self.start(), self.start())
        self.assertTrue(all(item['state'] in ('pending_hold', 'awaiting_reapproval') for item in starts))
        results = await asyncio.gather(self.accept(), self.accept())
        self.assertTrue(all(item['state'] == 'reapproved' for item in results))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM l15_change_outbox').fetchone()[0], 4)

    async def test_wrong_retained_bindings_never_activate_scope(self):
        self.provider.lost = 'held'
        await self.start()
        self.provider.lost = None
        original = self.provider.receipt
        for field in ['actor_id', 'source_scope_id', 'proposed_scope_id', 'retained_quote_id', 'retained_quote_revision', 'responsible_operator_id']:
            async def changed(change, approval, state):
                receipt = await original(change, approval, state)
                receipt[field] = 99 if field.endswith('_revision') else 'different-reference'
                return receipt
            self.provider.receipt = changed
            result = await self.store.resume('change-1', 'buyer-1', 'brand-1')
            self.assertEqual(result['state'], 'pending_hold')
            self.assertEqual(result['active_scope_id'], 'scope-4')


class RouteTests(unittest.IsolatedAsyncioTestCase):
    setUp = WorkflowTests.setUp
    tearDown = WorkflowTests.tearDown

    async def client(self):
        import httpx
        from fastapi import FastAPI
        import sys
        route_spec = importlib.util.spec_from_file_location('change_routes', ROOT / 'services/catalog/modules/job-changes/routes.py', submodule_search_locations=[str(ROOT / 'services/catalog/modules/job-changes')])
        routes = importlib.util.module_from_spec(route_spec)
        sys.modules[route_spec.name] = routes
        route_spec.loader.exec_module(routes)
        async def principal(request):
            return request.headers.get('X-Test-Actor', 'buyer-1'), request.headers.get('X-Test-Business', 'brand-1')
        app = FastAPI()
        app.include_router(routes.router_for(self.store, principal))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def test_route_rejects_unknown_fields_and_oversized_input(self):
        async with await self.client() as client:
            response = await client.post('/v1/jobs/job-1/changes', json={**asdict(self.change), 'evidence': 'private'})
            self.assertEqual(response.status_code, 409)
            response = await client.post('/v1/jobs/job-1/changes', content=b'x' * 8193)
            self.assertEqual(response.status_code, 409)

    async def test_route_reads_require_current_scope(self):
        async with await self.client() as client:
            self.assertEqual((await client.post('/v1/jobs/job-1/changes', json=asdict(self.change))).status_code, 200)
            response = await client.get('/v1/job-change-operations/change-1', headers={'X-Test-Business': 'brand-2'})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('scope-4', response.text)

    async def test_route_stamps_acceptance_and_duplicate_reconciles(self):
        async with await self.client() as client:
            await client.post('/v1/jobs/job-1/changes', json=asdict(self.change))
            body = asdict(self.approval)
            body['accepted_at'] = '2026-11-17T09:00:00Z'
            response = await client.post('/v1/job-change-operations/change-1/accept', json=body)
            self.assertEqual(response.json()['state'], 'reapproved')
            self.assertEqual(self.store.load('change-1')[2]['accepted_at'], self.provider.now)
            self.provider.now = '2026-11-17T10:00:00.500000Z'
            duplicate = await client.post('/v1/job-change-operations/change-1/accept', json=body)
            self.assertEqual(duplicate.json(), response.json())
