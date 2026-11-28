import asyncio
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[4]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


models = load('push_models', 'packages/contracts-comms/browser-push/models.py')
service = load('push_service', 'services/communications/modules/browser-push/service.py')
FIXTURE = json.loads((ROOT / 'packages/contracts-comms/browser-push/fixtures.json').read_text())


class BrowserPushTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'push.db')
        self.store = service.Store(self.path)
        self.identity = service.Identity('buyer-one', 'session-one', 1)
        self.notice = {'schema_version': 'browser-push.inbox.v1', 'recipient_id': 'buyer-one', 'available': True, 'kind': 'outbid',
                       'expires_at': '2026-11-17T00:00:00+00:00', 'private_evidence': 'excluded'}
        self.sent, self.outcome = [], 'sent'
        self.capability = 'a' * 64
        self.now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        self.notice_id = str(uuid4())
        self.configure()

    def configure(self):
        async def identity(_):
            return self.identity

        async def inbox(actor, notice):
            return self.notice

        async def delivery(subscription, payload, key):
            self.sent.append((subscription, payload, key))
            if self.outcome == 'timeout':
                raise TimeoutError()
            return self.outcome

        self.push = service.BrowserPush(self.store, identity, inbox, delivery,
            lambda endpoint: endpoint.startswith('https://push.beirut-time.invalid/'),
            lambda value: 'sealed:' + value, lambda value: value.removeprefix('sealed:'))

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    def command(self, **changes):
        values = dict(FIXTURE['command'])
        values.update(changes)
        return models.Command(**values)

    async def opt_in(self):
        return await self.push.command('credential', self.capability, self.command())

    async def dispatch(self, now=None):
        return await self.push.dispatch('credential', self.notice_id, FIXTURE['device_id'], now or self.now)

    async def test_durable_receipt_and_exact_retry_after_restart(self):
        first = await self.opt_in()
        self.store.close()
        self.store = service.Store(self.path)
        self.configure()
        self.assertEqual(first, await self.opt_in())
        self.assertEqual(first, await self.push.lookup('credential', FIXTURE['operation_id']))
        self.assertEqual(first, FIXTURE['success'])

    async def test_changed_duplicate_conflicts(self):
        await self.opt_in()
        with self.assertRaises(service.Conflict):
            await self.push.command('credential', self.capability, self.command(expected_revision=1))

    async def test_stale_revision(self):
        await self.opt_in()
        with self.assertRaises(service.Conflict):
            await self.push.command('credential', self.capability, self.command(operation_id=uuid4(), action='revoke'))

    async def test_refusal_keeps_inbox(self):
        for permission in ['denied', 'default']:
            with self.assertRaises(service.Denied):
                await self.push.command('credential', self.capability, self.command(permission=permission))
        self.assertTrue(self.notice['available'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM l20_push_devices').fetchone()[0], 0)

    async def test_failure_keeps_inbox_and_expires_endpoint(self):
        await self.opt_in()
        self.outcome = 'gone'
        self.assertEqual(await self.dispatch(), 'failed')
        self.assertTrue(self.notice['available'])
        row = self.store.db.execute('SELECT * FROM l20_push_devices').fetchone()
        self.assertFalse(row['active'])
        self.assertIsNone(row['subscription'])

    async def test_revoke_and_logout(self):
        await self.opt_in()
        await self.push.revoke_session('buyer-one', 'session-one')
        with self.assertRaises(service.Denied):
            await self.dispatch()
        self.assertTrue(self.notice['available'])

    async def test_command_revoke(self):
        await self.opt_in()
        result = await self.push.command('credential', self.capability, self.command(operation_id=uuid4(), action='revoke', expected_revision=1, subscription=None))
        self.assertEqual(result['state'], 'revoked')
        with self.assertRaises(service.Denied):
            await self.dispatch()

    async def test_account_switch_requires_capability_and_rebind(self):
        await self.opt_in()
        self.identity = service.Identity('buyer-two', 'session-two', 1)
        with self.assertRaises(service.Denied):
            await self.dispatch()
        with self.assertRaises(service.Denied):
            await self.push.command('credential', 'x' * 64, self.command(action='rebind', operation_id=uuid4(), expected_revision=1))
        await self.push.command('credential', self.capability, self.command(action='rebind', operation_id=uuid4(), expected_revision=1))
        with self.assertRaises(service.Denied):
            await self.dispatch()
        self.assertEqual(self.sent, [])

    async def test_access_revision_revokes_old_dispatch(self):
        await self.opt_in()
        self.identity = service.Identity('buyer-one', 'session-one', 2)
        with self.assertRaises(service.Denied):
            await self.dispatch()

    async def test_organization_denies(self):
        self.identity = service.Identity('buyer-one', 'session-one', 1, 'business')
        with self.assertRaises(service.Denied):
            await self.opt_in()

    async def test_authenticated_click_rechecks_access(self):
        self.assertEqual(await self.push.destination('credential', self.notice_id), {'url': '/inbox'})
        self.notice['available'] = False
        with self.assertRaises(service.Denied):
            await self.push.destination('credential', self.notice_id)
        self.notice['available'] = True
        self.identity = service.Identity('buyer-two', 'session-two', 1)
        with self.assertRaises(service.Denied):
            await self.push.destination('credential', self.notice_id)

    async def test_payload_has_no_private_source_fields(self):
        await self.opt_in()
        await self.dispatch()
        self.assertEqual(self.sent[0][1], {'schema_version': 'browser-push.v1', 'kind': 'notice'})
        self.assertNotIn('private_evidence', json.dumps(self.sent))

    async def test_all_four_notice_categories(self):
        await self.opt_in()
        for kind in ['outbid', 'win', 'message', 'action_needed']:
            self.notice_id = str(uuid4())
            self.notice['kind'] = kind
            self.assertEqual(await self.dispatch(), 'sent')

    async def test_duplicate_dispatch_after_restart(self):
        await self.opt_in()
        await self.dispatch()
        self.store.close()
        self.store = service.Store(self.path)
        self.configure()
        await self.dispatch()
        self.assertEqual(len(self.sent), 1)

    async def test_timeout_bounded_stable_retry_and_inbox(self):
        await self.opt_in()
        self.outcome = 'timeout'
        for _ in range(5):
            self.assertEqual(await self.dispatch(), 'pending')
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(len({row[2] for row in self.sent}), 1)
        self.assertTrue(self.notice['available'])

    async def test_before_equal_after_expiry(self):
        await self.opt_in()
        boundary = datetime.fromisoformat(self.notice['expires_at'])
        self.assertEqual(await self.dispatch(boundary), 'expired')
        self.assertEqual(await self.dispatch(boundary + timedelta(microseconds=1)), 'expired')
        self.assertEqual(await self.dispatch(boundary - timedelta(microseconds=1)), 'sent')

    async def test_missing_notice_and_bad_endpoint_deny(self):
        subscription = dict(endpoint='https://untrusted.invalid/path', p256dh='a' * 87, auth='b' * 22)
        with self.assertRaises(service.Denied):
            await self.push.command('credential', self.capability, self.command(subscription=subscription))
        await self.opt_in()
        self.notice = None
        with self.assertRaises(service.Denied):
            await self.dispatch()

    async def test_schema_bounds_and_forbids_identity(self):
        for values in [dict(expected_revision=True), dict(expected_revision=-1), dict(actor_id='buyer-two'), dict(subscription=dict(endpoint='https://x.invalid', p256dh='x', auth='b' * 22))]:
            with self.assertRaises(ValueError):
                self.command(**values)


    async def test_late_opt_in_cannot_resurrect_logged_out_session(self):
        await self.push.revoke_session('buyer-one', 'session-one')
        with self.assertRaises(service.Denied):
            await self.opt_in()
        self.store.close()
        self.store = service.Store(self.path)
        self.configure()
        with self.assertRaises(service.Denied):
            await self.opt_in()

    async def test_multiple_store_instances_share_revocation_lock(self):
        second = service.Store(self.path)
        try:
            self.assertIs(self.store.lock, second.lock)
            await self.opt_in()
            await self.push.revoke_session('buyer-one', 'session-one')
            self.assertEqual(second.db.execute('SELECT active FROM l20_push_devices').fetchone()[0], 0)
        finally:
            second.close()

    async def test_malformed_current_facts_are_unavailable(self):
        await self.opt_in()
        for value in [{}, {'schema_version': 'unknown'}, {**self.notice, 'expires_at': 'missing'}, {**self.notice, 'available': 1}]:
            self.notice = value
            with self.assertRaises(service.Pending):
                await self.dispatch()
        self.assertEqual(self.sent, [])

    async def test_published_negative_fixtures(self):
        for case, error in [('denied', service.Denied), ('stale', service.Conflict)]:
            body = models.Command.model_validate(FIXTURE[case]['request'])
            with self.assertRaises(error):
                await self.push.command('credential', self.capability, body)


class RouteTests(BrowserPushTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        import types
        package = types.ModuleType('push_runtime')
        package.__path__ = []
        sys.modules['push_runtime'] = package
        sys.modules['push_runtime.service'] = service
        routes = load('push_runtime.routes', 'services/communications/modules/browser-push/routes.py')
        from fastapi import FastAPI
        import httpx
        app = FastAPI()

        async def credential(request):
            if request.headers.get('authorization') != 'Bearer test':
                from fastapi import HTTPException
                raise HTTPException(401)
            return 'credential'

        async def capability(request):
            return self.capability

        app.include_router(routes.build_router(self.push, models.Command, credential, capability))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://beirut-time.invalid', headers={'Authorization': 'Bearer test'})

    async def asyncTearDown(self):
        await self.client.aclose()
        await super().asyncTearDown()

    async def test_route_success_duplicate_and_lookup(self):
        body = self.command().model_dump(mode='json')
        first = await self.client.post('/v1/browser-push/devices', json=body)
        second = await self.client.post('/v1/browser-push/devices', json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        lookup = await self.client.get('/v1/browser-push/operations/' + body['operation_id'])
        self.assertEqual(lookup.json(), first.json())
        self.assertNotIn('endpoint', first.text)

    async def test_route_bounds_and_safe_validation(self):
        response = await self.client.post('/v1/browser-push/devices', content='x' * 4097)
        self.assertEqual(response.status_code, 413)
        response = await self.client.post('/v1/browser-push/devices', content='private malformed body')
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('private malformed', response.text)

    async def test_route_denied_stale_and_unauthenticated(self):
        response = await self.client.post('/v1/browser-push/devices', json=self.command(permission='denied').model_dump(mode='json'))
        self.assertEqual(response.status_code, 403)
        await self.opt_in()
        response = await self.client.post('/v1/browser-push/devices', json=self.command(operation_id=uuid4(), expected_revision=0, action='revoke').model_dump(mode='json'))
        self.assertEqual(response.status_code, 409)
        response = await self.client.get('/v1/browser-push/devices/' + FIXTURE['device_id'], headers={'Authorization': ''})
        self.assertEqual(response.status_code, 401)

    async def test_missing_provider_config_unavailable(self):
        response = await self.client.get('/v1/browser-push/config')
        self.assertEqual(response.status_code, 503)
