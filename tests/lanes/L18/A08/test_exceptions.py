import asyncio
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load('exception_contract', 'packages/contracts-trust/auction-exceptions/current.py')
service = load('exception_service', 'services/trust/modules/auction-exceptions/service.py')
adapter = load('exception_adapter', 'services/trust/modules/auction-exceptions/adapter.py')


class CanonicalFixture:
    def __init__(self):
        self.receipts = {}
        self.calls = 0
        self.allowed = True
        self.lost = False
        self.boundary = -1
        self.bids = 1
        self.revision = 4

    async def authorize(self, command, principal):
        if not self.allowed or principal.get('permission') is not True:
            raise service.Denied('permission_denied')
        return 'responsible-operator'

    async def execute(self, command):
        self.calls += 1
        key = command['operation_id']
        if key not in self.receipts:
            state, code = 'acknowledged', 'competition_recomputed'
            if command['expected_revision'] != self.revision:
                state, code = 'denied', 'stale_revision'
            elif command['action'] == 'seller_end':
                state, code = ('denied', 'bids_present') if self.bids else ('acknowledged', 'seller_ended')
            elif self.boundary >= 0:
                state, code = 'pending', 'order_exception_recorded'
            self.receipts[key] = dict(command, schema_version='auction-exceptions.v1', state=state,
                                      code=code, revision=self.revision)
        if self.lost:
            self.lost = False
            raise TimeoutError()
        return self.receipts[key]


class ExceptionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.provider = CanonicalFixture()
        self.path = str(Path(self.folder.name) / 'receipts.db')
        self.svc = service.Service(self.path, self.provider, lambda: datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.command = contract.Command('op-1', 'auction-1', 'watch-1', 'operator-1', 'business-1', 4,
                                        'retract', 'Recorded independent reason', 'bidder-1', 'quote-1', 2, 1, 3)
        self.principal = dict(actor_id='operator-1', organization_id='business-1', permission=True)

    async def submit(self, **changes):
        return await self.svc.submit(replace(self.command, **changes), self.principal)

    async def test_before_equal_after(self):
        for boundary in (-1, 0, 1):
            self.provider.boundary = boundary
            result = await self.submit(operation_id=f'op-{boundary}')
            self.assertEqual(result['code'], 'competition_recomputed' if boundary < 0 else 'order_exception_recorded')
            self.assertEqual(result['state'], 'acknowledged' if boundary < 0 else 'pending')
            if boundary >= 0:
                self.assertEqual(result['next_actor'], 'responsible-operator')
                self.assertIsNotNone(result['next_review_at'])

    async def test_seller_end_requires_zero_bids(self):
        self.assertEqual((await self.submit(action='seller_end'))['code'], 'bids_present')
        self.provider.bids = 0
        self.assertEqual((await self.submit(action='seller_end', operation_id='op-2'))['code'], 'seller_ended')

    async def test_stale(self):
        self.assertEqual((await self.submit(expected_revision=3))['code'], 'stale_revision')

    async def test_future_revision_stale_denial_survives_restart(self):
        command = replace(self.command, expected_revision=5)
        result = await self.svc.submit(command, self.principal)
        self.assertEqual((result['state'], result['code'], result['revision']), ('denied', 'stale_revision', 4))
        self.svc = service.Service(self.path, self.provider)
        self.assertEqual(await self.svc.lookup(command, self.principal), result)
        self.assertEqual(await self.svc.submit(command, self.principal), result)
        self.assertEqual(self.provider.calls, 1)

    async def test_lower_revision_success_remains_uncertain(self):
        await self.submit()
        self.provider.receipts['lower'] = dict(self.provider.receipts['op-1'], operation_id='lower', revision=3)
        self.assertEqual((await self.submit(operation_id='lower'))['state'], 'pending')

    def test_reason_codepoint_length(self):
        with self.assertRaises(ValueError):
            replace(self.command, reason='🔒' * 5)
        self.assertEqual(replace(self.command, reason='🔒' * 10).reason, '🔒' * 10)

    async def test_wrong_organization_and_actor(self):
        for changes in ({'organization_id':'other'}, {'actor_id':'other'}):
            with self.assertRaises(service.Denied):
                await self.submit(**changes)
        self.assertEqual(self.provider.calls, 0)

    async def test_revocation_blocks_lookup_and_duplicate(self):
        await self.submit()
        self.provider.allowed = False
        with self.assertRaises(service.Denied):
            await self.svc.lookup(self.command, self.principal)
        with self.assertRaises(service.Denied):
            await self.submit()

    async def test_duplicate_and_conflicting_retry(self):
        first = await self.submit()
        self.assertEqual(first, await self.submit())
        self.assertEqual(self.provider.calls, 1)
        with self.assertRaises(service.Denied):
            await self.submit(reason='A different recorded reason')

    async def test_lost_response_restart(self):
        self.provider.lost = True
        result = await self.submit()
        self.assertEqual(result['state'], 'pending')
        self.svc = service.Service(self.path, self.provider)
        self.assertEqual((await self.svc.lookup(self.command, self.principal))['state'], 'pending')
        self.assertEqual((await self.submit())['state'], 'acknowledged')
        self.svc = service.Service(self.path, self.provider)
        self.assertEqual((await self.svc.lookup(self.command, self.principal))['state'], 'acknowledged')
        self.assertEqual(len(self.provider.receipts), 1)

    async def test_unbound_receipt_fails_closed(self):
        await self.submit()
        self.provider.receipts['op-2'] = dict(self.provider.receipts['op-1'])
        self.assertEqual((await self.submit(operation_id='op-2'))['state'], 'pending')

    def test_bound_input(self):
        for changes in ({'reason':'short'}, {'expected_revision':True}, {'reason':'x'*2001}, {'target_bidder_id':None}):
            with self.assertRaises(ValueError):
                replace(self.command, **changes)

    async def test_published_fixtures(self):
        fixtures = json.loads((ROOT / 'packages/contracts-trust/auction-exceptions/fixtures.json').read_text())
        for case in fixtures['cases']:
            with self.subTest(case=case['name']):
                command = contract.Command(**dict(case['request'], operation_id=case['name']))
                self.provider.receipts[case['name']] = dict(case['response'], operation_id=case['name'])
                result = await self.svc.submit(command, self.principal)
                self.assertEqual(result, dict(case['response'], operation_id=case['name']))
                self.assertNotIn('reason', result)
                self.assertNotIn('target_bidder_id', result)

    async def test_pending_review_does_not_restart(self):
        self.provider.boundary = 0
        first = await self.submit()
        self.svc.clock = lambda: datetime(2026, 11, 18, 23, tzinfo=timezone.utc)
        second = await self.submit()
        self.assertEqual(first['next_review_at'], second['next_review_at'])
        self.assertEqual(first['escalation_at'], second['escalation_at'])

    async def test_economics_bindings(self):
        await self.submit()
        for field in ('quote_id', 'quote_revision', 'policy_revision', 'assignment_revision'):
            with self.subTest(field=field):
                key = 'mismatch-' + field
                receipt = dict(self.provider.receipts['op-1'], operation_id=key)
                receipt[field] = 'other' if field == 'quote_id' else 99
                self.provider.receipts[key] = receipt
                self.assertEqual((await self.submit(operation_id=key))['state'], 'pending')

    async def test_adapter_bounds(self):
        boundary = adapter.Adapter(self.svc, contract.Command)
        with self.assertRaises(ValueError):
            await boundary.command(b'x' * 16385, self.principal)
        result = await boundary.command(json.dumps(self.command.payload()).encode(), self.principal)
        self.assertEqual(result['state'], 'acknowledged')
        self.assertEqual(await boundary.operation('op-1', self.command, self.principal), result)
        with self.assertRaises(ValueError):
            await boundary.operation('other', self.command, self.principal)

    async def test_permission_timeout_is_not_execution(self):
        async def delayed(command, principal):
            await asyncio.sleep(2)
        self.provider.authorize = delayed
        with self.assertRaises(TimeoutError):
            await self.submit()
        self.assertEqual(self.provider.calls, 0)
