"""Pure composition checks; no database or destination is contacted."""
import asyncio
import json
import unittest
from pathlib import Path

import httpx
from bt_bulkheads import DependencyClient, Unavailable

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = json.loads((ROOT / 'contracts/registrations/L16.json').read_text())['wiring']


class CompositionTests(unittest.TestCase):
    def test_fixture_envelope(self):
        schema = MANIFEST['fixture_schema']
        for fixture in MANIFEST['fixtures']:
            self.assertEqual(set(fixture), set(schema['required']))
            self.assertEqual(fixture['schema_version'], 'lane-wiring-result.v1')
            for field, rule in schema['properties'].items():
                value = fixture[field]
                if 'enum' in rule:
                    self.assertIn(value, rule['enum'])
                if rule.get('type') == 'string':
                    self.assertIsInstance(value, str)
                    self.assertTrue(value)
                if rule.get('type') == ['integer', 'null'] and value is not None:
                    self.assertIs(type(value), int)
                    self.assertGreaterEqual(value, 0)
                if rule.get('type') == ['string', 'null'] and value is not None:
                    self.assertIsInstance(value, str)
            if fixture['state'] == 'pending':
                self.assertTrue(fixture['pending_reason'])
                self.assertTrue(fixture['next_actor'])
                self.assertTrue(fixture['next_review_at'])

    def test_additive_full_module_plan(self):
        modules = {}
        for path in (ROOT / 'services').rglob('module.json'):
            if '_template' in path.parts:
                continue
            data = json.loads(path.read_text())
            self.assertNotIn(data['id'], modules)
            modules[data['id']] = data
            migrations = data.get('migrations', [])
            self.assertEqual(migrations, sorted(set(migrations)))
            for migration in migrations:
                self.assertTrue((path.parent / migration).is_file())
                self.assertTrue(Path(migration).name.startswith(data['id'][:3] + '_'))
        for operation in MANIFEST['operations'].values():
            self.assertIn(operation['module'], modules)
            self.assertNotIn('internal', operation['path'])
        order = MANIFEST['migration_policy']['order']
        self.assertLess(order.index('apply-additive-migrations'), order.index('mount-receivers'))
        self.assertLess(order.index('verify-subscriptions'), order.index('enable-destinations'))
        self.assertFalse(MANIFEST['delivery']['enabled'])
        self.assertIn(MANIFEST['delivery']['receiver'], modules)


class DependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_circuit_and_independent_dependency(self):
        async def slow(request):
            await asyncio.Event().wait()
        async def ready(request):
            return httpx.Response(200, json={'state': 'saved'})
        failed = DependencyClient('catalog', 'http://catalog', timeout=.01,
                                  failure_threshold=1, transport=httpx.MockTransport(slow))
        healthy = DependencyClient('identity', 'http://identity', transport=httpx.MockTransport(ready))
        try:
            self.assertEqual(await failed.request('GET', '/v1/current'), Unavailable('catalog', 'timeout'))
            self.assertEqual((await failed.request('GET', '/v1/current')).reason, 'circuit_open')
            self.assertEqual((await healthy.request('GET', '/v1/current')).status_code, 200)
            self.assertEqual(MANIFEST['result_policy']['timeout'], 'pending')
        finally:
            await failed.aclose()
            await healthy.aclose()

    async def test_saturation_and_denied_stale_are_not_success(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(request):
            entered.set()
            await release.wait()
            return httpx.Response(403)
        client = DependencyClient('identity', 'http://identity', concurrency=1, transport=httpx.MockTransport(held))
        task = asyncio.create_task(client.request('GET', '/v1/current'))
        try:
            await entered.wait()
            self.assertEqual((await client.request('GET', '/v1/current')).reason, 'saturated')
            release.set()
            self.assertEqual((await task).status_code, 403)
            self.assertEqual(client._failures, 0)
            client.client._transport = httpx.MockTransport(lambda request: httpx.Response(409))
            self.assertEqual((await client.request('GET', '/v1/current')).status_code, 409)
            self.assertEqual(client._failures, 0)
        finally:
            release.set()
            await task
            await client.aclose()

    async def test_response_budget_and_origin(self):
        client = DependencyClient('catalog', 'http://catalog', transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'x' * (2 * 1024 * 1024 + 1))))
        try:
            self.assertEqual((await client.request('GET', '/v1/current')).reason, 'upstream')
            for path in ['https://elsewhere.invalid/v1/current', '//elsewhere.invalid/v1/current']:
                with self.assertRaises(ValueError):
                    await client.request('GET', path)
        finally:
            await client.aclose()
