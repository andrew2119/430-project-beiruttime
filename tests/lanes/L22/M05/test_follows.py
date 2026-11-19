import asyncio
import json
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load('follow_contract', 'packages/contracts-comms/seller-follows/schema.py')
store_module = load('follow_store', 'services/communications/modules/seller-follows/store.py')
routes = load('follow_routes', 'services/communications/modules/seller-follows/routes.py')


class Follows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.actor, self.seller, self.watch = map(str, (uuid4(), uuid4(), uuid4()))
        self.now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        self.principal = dict(actor_id=self.actor, organization_id=None, active=True, roles=['buyer'])
        self.public = True
        self.facts = None
        self.delay = 0
        self.store = self.reopen()

    def reopen(self):
        async def identity(token):
            await asyncio.sleep(self.delay)
            return self.principal

        async def catalog(seller, watch):
            return self.facts if watch else dict(public=self.public, seller_id=seller)

        return store_module.Store(Path(self.temp.name) / 'state.sqlite', identity, catalog, lambda: self.now)

    def command(self, **kwargs):
        return contract.Command(schema_version='seller-follows.v1', operation_id=uuid4(), actor_id=self.actor,
                                seller_id=self.seller, expected_revision=kwargs.pop('revision', 0),
                                following=kwargs.pop('following', True), alerts_enabled=kwargs.pop('alerts', True), **kwargs)

    def event(self, when=None, revision=1):
        event = contract.Publication(schema_version='catalog.publication.v1', event_id=uuid4(), seller_id=self.seller,
                                     watch_id=self.watch, revision=revision, published_at=when or self.now, sample=True)
        self.facts = dict(public=self.public, seller_id=self.seller, watch_id=self.watch, revision=revision,
                          published_at=store_module.instant(event.published_at), sample=True)
        return event

    async def test_restart_receipt_and_duplicate(self):
        command = self.command()
        receipt = await self.store.command('current', command)
        self.store = self.reopen()
        self.assertEqual(receipt, await self.store.command('current', command))
        self.assertEqual(receipt, await self.store.operation('current', command.operation_id))
        self.assertEqual((await self.store.page('current'))['total'], 1)

    async def test_conflicting_operation_and_stale(self):
        command = self.command()
        await self.store.command('current', command)
        with self.assertRaises(HTTPException) as error:
            await self.store.command('current', command.model_copy(update={'alerts_enabled': False}))
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            await self.store.command('current', self.command())

    async def test_scope_and_current_revocation(self):
        command = self.command()
        await self.store.command('current', command)
        self.principal['organization_id'] = str(uuid4())
        for action in [self.store.page('current'), self.store.command('current', command), self.store.operation('current', command.operation_id)]:
            with self.assertRaises(HTTPException) as error:
                await action
            self.assertEqual(error.exception.status_code, 403)
        self.principal['organization_id'] = None
        self.principal['active'] = False
        with self.assertRaises(HTTPException):
            await self.store.notices('current')

    async def test_other_actor_cannot_read_receipt_or_write(self):
        command = self.command()
        await self.store.command('current', command)
        self.principal['actor_id'] = str(uuid4())
        self.assertEqual((await self.store.page('current'))['total'], 0)
        with self.assertRaises(HTTPException):
            await self.store.operation('current', command.operation_id)
        with self.assertRaises(HTTPException):
            await self.store.command('current', command)

    async def test_timeout_is_not_success(self):
        self.delay = .4
        with self.assertRaises(HTTPException) as error:
            await self.store.command('current', self.command())
        self.assertEqual(error.exception.status_code, 503)
        self.delay = 0
        self.assertEqual((await self.store.page('current'))['total'], 0)

    async def test_one_notice_and_source_access_rechecked(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        event = self.event()
        self.assertEqual(await self.store.publication(event), 1)
        self.assertEqual(await self.store.publication(event.model_copy(update={'event_id': uuid4()})), 0)
        self.store = self.reopen()
        notices = await self.store.notices('current')
        self.assertEqual(notices['total'], 1)
        notice = notices['items'][0]['id']
        self.assertEqual((await self.store.destination('current', notice))['url'], '/watches/' + self.watch)
        self.facts['public'] = False
        with self.assertRaises(HTTPException):
            await self.store.destination('current', notice)

    async def test_before_equal_after_follow_boundary(self):
        await self.store.command('current', self.command())
        followed = self.now
        self.now += timedelta(seconds=2)
        for revision, delta, expected in [(1,-1,0),(2,0,0),(3,1,1)]:
            self.assertEqual(await self.store.publication(self.event(followed+timedelta(seconds=delta), revision)), expected)

    async def test_old_event_after_unfollow_and_refollow(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        old = self.event()
        await self.store.command('current', self.command(revision=1, following=False))
        self.assertEqual(await self.store.publication(old), 0)
        self.now += timedelta(seconds=1)
        await self.store.command('current', self.command(revision=2))
        self.assertEqual(await self.store.publication(old), 0)
        self.assertEqual((await self.store.notices('current'))['total'], 0)
        self.assertEqual((await self.store.status('current', UUID(self.seller)))['revision'], 3)

    async def test_preference_reenable_excludes_old_publications(self):
        await self.store.command('current', self.command(alerts=False))
        self.now += timedelta(seconds=1)
        event = self.event()
        self.now += timedelta(seconds=1)
        await self.store.command('current', self.command(revision=1))
        self.assertEqual(await self.store.publication(event), 0)

    async def test_private_and_stale_sources(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        self.public = False
        event = self.event()
        self.assertEqual(await self.store.publication(event), 0)
        self.assertEqual((await self.store.notices('current'))['total'], 0)
        self.facts['public'] = True
        self.facts['revision'] = 7
        with self.assertRaises(HTTPException):
            await self.store.publication(event)

    async def test_thousand_rows_complete_pagination(self):
        with self.store.connect() as db:
            db.executemany('INSERT INTO follows VALUES(?,?,?,?,?,?)', [(self.actor,str(UUID(int=i+1)),1,0,1,store_module.instant(self.now)) for i in range(1000)])
        ids = []
        for page in range(20):
            result = await self.store.page('current', page)
            self.assertEqual(result['total'], 1000)
            ids.extend(item['seller_id'] for item in result['items'])
        self.assertEqual(len(set(ids)), 1000)
        self.assertEqual((await self.store.page('current',20))['items'], [])
        with self.assertRaises(HTTPException):
            await self.store.page('current',-1)

    async def test_schema_and_route_contract(self):
        with self.assertRaises(ValidationError):
            self.command(organization_id=uuid4())
        with self.assertRaises(ValidationError):
            self.command(revision=True)
        with self.assertRaises(ValidationError):
            self.event(datetime(2026, 11, 17))
        self.assertEqual(len(routes.create_router(self.store).routes), 7)

    async def test_retained_retry_survives_source_removal(self):
        command = self.command()
        receipt = await self.store.command('current', command)
        self.public = False
        self.assertEqual(await self.reopen().command('current', command), receipt)

    async def test_deterministic_fixtures(self):
        fixture = json.loads((ROOT / 'packages/contracts-comms/seller-follows/fixtures.json').read_text())
        self.principal = fixture['principal']
        command = contract.Command(**fixture['command'])
        self.assertEqual(await self.store.command('current', command), fixture['receipt'])
        self.assertEqual(await self.reopen().command('current', command), fixture['receipt'])
        contract.Publication(**fixture['publication'])
        for case in fixture['cases'][1:3]:
            with self.assertRaises(HTTPException) as error:
                await self.store.command('current', contract.Command(**case['command']))
            self.assertEqual(error.exception.status_code, case['expected_status'])

    async def test_missing_source_remains_retryable(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        event = self.event()
        good = self.facts
        for missing in [None, {}, {'public': 'yes'}]:
            self.facts = missing
            with self.assertRaises(HTTPException) as error:
                await self.store.publication(event)
            self.assertEqual(error.exception.status_code, 503)
        self.facts = good
        self.assertEqual(await self.store.publication(event), 1)

    async def test_route_adapter_roundtrip_and_denial(self):
        import httpx
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(routes.create_router(self.store))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            command = self.command()
            response = await client.put('/v1/seller-follows', json=command.model_dump(mode='json'), headers={'authorization':'current'})
            self.assertEqual(response.status_code, 200)
            receipt = await client.get('/v1/seller-follows/operations/' + str(command.operation_id), headers={'authorization':'current'})
            self.assertEqual(receipt.json(), response.json())
            invalid = await client.get('/v1/seller-follows?page=-1', headers={'authorization':'current'})
            self.assertEqual(invalid.status_code, 422)
            self.principal['organization_id'] = str(uuid4())
            denied = await client.get('/v1/seller-follows', headers={'authorization':'current'})
            self.assertEqual(denied.status_code, 403)

    async def test_notice_read_clear_are_independent_durable_and_idempotent(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        await self.store.publication(self.event())
        notice = (await self.store.notices('current'))['items'][0]
        self.assertIsNone(notice['read_at'])
        self.assertIsNone(notice['cleared_at'])
        def action(kind, revision):
            return contract.NoticeCommand(schema_version='seller-follows.v1', operation_id=uuid4(),
                actor_id=self.actor, notice_id=notice['id'], expected_revision=revision, action=kind)
        read = action('read', 1)
        receipt = await self.store.notice_command('current', read)
        self.assertIsNotNone(receipt['read_at'])
        self.assertIsNone(receipt['cleared_at'])
        self.store = self.reopen()
        self.assertEqual(await self.store.notice_command('current', read), receipt)
        self.assertEqual(await self.store.operation('current', read.operation_id), receipt)
        self.assertEqual((await self.store.notices('current'))['total'], 1)
        with self.assertRaises(HTTPException) as error:
            await self.store.notice_command('current', action('clear', 1))
        self.assertEqual(error.exception.status_code, 409)
        clear = action('clear', 2)
        cleared = await self.store.notice_command('current', clear)
        self.assertEqual(cleared['read_at'], receipt['read_at'])
        self.assertIsNotNone(cleared['cleared_at'])
        self.assertEqual((await self.reopen().notices('current'))['total'], 0)
        self.assertEqual(await self.reopen().notice_command('current', clear), cleared)
        self.assertTrue((await self.store.status('current', self.seller))['following'])
        self.assertEqual(await self.store.publication(self.event()), 0)

    async def test_clear_without_read_and_scope_timeout(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        await self.store.publication(self.event())
        notice = (await self.store.notices('current'))['items'][0]
        command = contract.NoticeCommand(schema_version='seller-follows.v1', operation_id=uuid4(),
            actor_id=self.actor, notice_id=notice['id'], expected_revision=1, action='clear')
        self.delay = .4
        with self.assertRaises(HTTPException) as error:
            await self.store.notice_command('current', command)
        self.assertEqual(error.exception.status_code, 503)
        self.delay = 0
        self.principal['organization_id'] = str(uuid4())
        with self.assertRaises(HTTPException) as error:
            await self.store.notice_command('current', command)
        self.assertEqual(error.exception.status_code, 403)
        self.principal['organization_id'] = None
        self.principal['actor_id'] = str(uuid4())
        other = command.model_copy(update={'actor_id': UUID(self.principal['actor_id'])})
        with self.assertRaises(HTTPException) as error:
            await self.store.notice_command('current', other)
        self.assertEqual(error.exception.status_code, 404)
        self.principal['actor_id'] = self.actor
        receipt = await self.store.notice_command('current', command)
        self.assertIsNone(receipt['read_at'])
        self.assertIsNotNone(receipt['cleared_at'])
        with self.assertRaises(HTTPException) as error:
            await self.store.notice_command('current', command.model_copy(update={'action': 'read'}))
        self.assertEqual(error.exception.status_code, 409)
        self.principal['active'] = False
        with self.assertRaises(HTTPException) as error:
            await self.store.notice_command('current', command)
        self.assertEqual(error.exception.status_code, 403)

    async def test_notice_route_read_and_clear(self):
        import httpx
        from fastapi import FastAPI
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        await self.store.publication(self.event())
        notice = (await self.store.notices('current'))['items'][0]
        app = FastAPI()
        app.include_router(routes.create_router(self.store))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for revision, action in [(1, 'read'), (2, 'clear')]:
                command = dict(schema_version='seller-follows.v1', operation_id=str(uuid4()),
                    actor_id=self.actor, notice_id=notice['id'], expected_revision=revision, action=action)
                response = await client.put('/v1/seller-follows/notices', json=command, headers={'authorization': 'current'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['revision'], revision + 1)

    async def test_existing_notice_migrates_to_unread_without_republication(self):
        await self.store.command('current', self.command())
        self.now += timedelta(seconds=1)
        event = self.event()
        await self.store.publication(event)
        with self.store.connect() as db:
            for column in ['read_at', 'cleared_at', 'notice_revision']:
                db.execute(f'ALTER TABLE notices DROP COLUMN {column}')
        self.store = self.reopen()
        notice = (await self.store.notices('current'))['items'][0]
        self.assertIsNone(notice['read_at'])
        self.assertIsNone(notice['cleared_at'])
        self.assertEqual(notice['notice_revision'], 1)
        self.assertEqual(await self.store.publication(event), 0)

    async def test_notice_operation_fixtures(self):
        fixture = json.loads((ROOT / 'packages/contracts-comms/seller-follows/fixtures.json').read_text())
        self.principal = fixture['principal']
        await self.store.command('current', contract.Command(**fixture['command']))
        event = contract.Publication(**fixture['publication'])
        self.now += timedelta(seconds=1)
        self.facts = dict(public=True, seller_id=str(event.seller_id), watch_id=str(event.watch_id),
            revision=event.revision, published_at=store_module.instant(event.published_at), sample=event.sample)
        self.assertEqual(await self.store.publication(event), 1)
        self.now += timedelta(seconds=1)
        for case in fixture['notice_operation_cases']:
            command = contract.NoticeCommand(**case['command'])
            if 'expected_status' in case:
                with self.assertRaises(HTTPException) as error:
                    await self.store.notice_command('current', command)
                self.assertEqual(error.exception.status_code, case['expected_status'])
            else:
                self.assertEqual(await self.store.notice_command('current', command), case['expected'])
                self.assertEqual(await self.reopen().notice_command('current', command), case['expected'])
