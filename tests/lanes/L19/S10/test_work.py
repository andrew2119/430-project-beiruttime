import asyncio
import importlib.util
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

c = load('work_v1', 'packages/contracts-service/authorized-work/v1.py')
f = load('work_fixture', 'packages/contracts-service/authorized-work/fixtures.py')
s = load('work_store', 'services/service-operations/modules/authorized-work/store.py')

class Provider:
    def __init__(self):
        self.auth = f.authority()
        self.timeout = False
        self.holds = []
    async def authorize(self, *args):
        return self.auth
    async def context(self, *args):
        return self.auth
    async def hold(self, body):
        self.holds.append(body.operation_id)
        if self.timeout:
            raise TimeoutError()
        return dict(operation_id=body.operation_id,subject_id=body.subject_id,watch_id=body.watch_id,
            source_revision=body.source_revision,actor_id=body.actor_id,organization_id=body.organization_id,
            quote_id=body.quote_id,quote_revision=body.quote_revision,policy_revision=body.policy_revision,state='held',work_held=True,handover_held=True,
            payout_held=True,invalidates_quality=True,hold_revision=2)

class WorkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'work.sqlite')
        self.provider = Provider()
        self.store = s.Store(self.path, self.provider, c)
        self.body = c.Command(**f.command())
    async def run_command(self, body=None, now=None):
        return await self.store.execute(body or self.body, f.identity(4), f.identity(5), now or f.NOW)
    def change(self, **changes):
        return c.Command(**{**f.command(), **changes})
    async def test_actual_work_readings_parts_and_duplicate(self):
        body = self.change(parts=[dict(line_id=f.identity(7),reference='Synthetic part',quantity=1,disposition='installed')])
        result = await self.run_command(body)
        self.assertEqual(result['state'], 'recorded')
        self.assertEqual(result, await self.run_command(body))
        history = await self.store.observations(body, f.identity(4), f.identity(5), f.NOW)
        self.assertEqual(history['total'], 1)
        self.assertTrue(history['complete'])
        self.assertFalse(history['release_eligible'])
        self.assertEqual(history['items'][0]['readings'][0]['seconds_per_day'],12)
    async def test_current_denied_duplicate_and_read(self):
        await self.run_command()
        self.provider.auth['state']='denied'
        with self.assertRaisesRegex(s.Rejected,'denied'):
            await self.run_command()
        with self.assertRaisesRegex(s.Rejected,'denied'):
            await self.store.lookup(self.body.operation_id, f.identity(4), f.identity(5), f.NOW)
    async def test_wrong_organization_actor_and_source(self):
        for field in ('organization_id','actor_id','source_revision','watch_id','quote_revision','policy_revision','next_actor'):
            with self.subTest(field=field):
                value = 2 if field.endswith('revision') else f.identity(99)
                with self.assertRaises(s.Rejected):
                    await self.run_command(self.change(**{field:value}))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_operations').fetchone()[0],0)
    async def test_stale_and_conflicting_duplicate(self):
        await self.run_command()
        with self.assertRaisesRegex(s.Rejected,'duplicate_conflict'):
            await self.run_command(self.change(note='Changed'))
        with self.assertRaisesRegex(s.Rejected,'stale'):
            await self.run_command(self.change(operation_id=f.identity(88)))
    async def test_incident_after_work_pending_restart_and_hold(self):
        await self.run_command()
        incident=self.change(operation_id=f.identity(8),expected_revision=1,kind='damage',line_ids=[],readings=[])
        self.provider.timeout=True
        result=await self.run_command(incident)
        self.assertEqual(result['state'],'pending')
        self.store=s.Store(self.path,self.provider,c)
        self.assertEqual((await self.store.lookup(incident.operation_id,f.identity(4),f.identity(5),f.NOW))['state'],'pending')
        with self.assertRaisesRegex(s.Rejected,'paused'):
            await self.run_command(self.change(operation_id=f.identity(9),expected_revision=2))
        self.provider.timeout=False
        result=await self.run_command(incident)
        self.assertEqual(result['state'],'paused')
        self.assertEqual(result['hold_revision'],2)
        self.assertFalse(result['release_eligible'])
        self.assertEqual(self.provider.holds,[incident.operation_id,incident.operation_id])
        self.assertEqual((await self.store.observations(incident,f.identity(4),f.identity(5),f.NOW))['total'],2)
    async def test_unaccepted_line_unpaid_and_declined_return(self):
        with self.assertRaisesRegex(s.Rejected,'unaccepted_line'):
            await self.run_command(self.change(line_ids=[f.identity(99)]))
        self.provider.auth['payment_state']='unpaid'
        with self.assertRaisesRegex(s.Rejected,'denied'):
            await self.run_command()
        self.provider.auth['state']='declined'
        result=await self.run_command(self.change(operation_id=f.identity(40),kind='declined_return',line_ids=[],readings=[]))
        self.assertEqual(result['state'],'paused')
    async def test_authority_before_equal_after(self):
        deadline=self.provider.auth['valid_until']
        for delta,allowed in [(-1,True),(0,False),(1,False)]:
            now=deadline+timedelta(seconds=delta)
            if allowed:
                await self.store.authority(self.body,f.identity(4),f.identity(5),now)
            else:
                with self.assertRaisesRegex(s.Rejected,'denied'):
                    await self.store.authority(self.body,f.identity(4),f.identity(5),now)
    async def test_followup_boundary_and_future(self):
        for delta,allowed in [(-1,False),(0,False),(1,True)]:
            body=self.change(operation_id=f.identity(30+delta),next_review_at=f.NOW+timedelta(seconds=delta))
            if allowed:
                await self.run_command(body)
            else:
                with self.assertRaisesRegex(s.Rejected,'review_due'):
                    await self.run_command(body)
        with self.assertRaisesRegex(s.Rejected,'future_observation'):
            await self.run_command(self.change(observed_at=f.NOW+timedelta(seconds=1)))
    async def test_malformed_hold_never_confirms(self):
        async def wrong(body):
            return {'state':'held'}
        self.provider.hold=wrong
        result=await self.run_command(self.change(kind='loss',line_ids=[],readings=[]))
        self.assertEqual(result['state'],'pending')
    def test_bounds_and_locale_keys(self):
        for changes in [dict(note='x'*2001),dict(parts=[dict(line_id=f.identity(7),reference='x',quantity=True,disposition='installed')]),dict(expected_revision=True)]:
            with self.assertRaises(ValueError):
                self.change(**changes)
        base=ROOT/'web/features/authorized-work'
        self.assertEqual(set(json.loads((base/'en.json').read_text())),set(json.loads((base/'ar.json').read_text())))


    async def test_waiting_and_current_scope_completeness(self):
        waiting=self.change(kind='waiting_parts',line_ids=[],readings=[])
        await self.run_command(waiting)
        await self.run_command(self.change(operation_id=f.identity(21),expected_revision=1))
        self.provider.auth['source_revision']=2
        body=self.change(source_revision=2)
        history=await self.store.observations(body,f.identity(4),f.identity(5),f.NOW)
        self.assertFalse(history['complete'])
        self.assertEqual(history['total'],2)
    async def test_history_uses_current_watch_partition(self):
        await self.run_command()
        self.provider.auth['watch_id'] = f.identity(90)
        with self.assertRaisesRegex(s.Rejected, 'denied'):
            await self.store.lookup(self.body.operation_id, f.identity(4), f.identity(5), f.NOW)
        history = await self.store.history(self.body.subject_id, f.identity(4), f.identity(5), f.NOW)
        self.assertEqual(history['items'], [])
        self.assertEqual(history['total'], 0)
        self.assertIsNone(history['next_offset'])
        self.assertFalse(history['complete'])
        current = self.change(operation_id=f.identity(91), watch_id=f.identity(90),
                              expected_revision=1)
        await self.run_command(current)
        history = await self.store.history(self.body.subject_id, f.identity(4), f.identity(5), f.NOW)
        self.assertEqual(history['total'], 1)
        self.assertEqual([row['operation_id'] for row in history['items']], [str(current.operation_id)])
        self.assertTrue(history['complete'])
        self.assertIsNone(history['next_offset'])

    async def test_real_pagination_thousand_rows(self):
        for n in range(1000):
            await self.run_command(self.change(operation_id=f.identity(100+n),expected_revision=n))
        history=await self.store.history(self.body.subject_id,f.identity(4),f.identity(5),f.NOW,950)
        self.assertEqual(history['total'],1000)
        self.assertEqual(len(history['items']),50)
        self.assertIsNone(history['next_offset'])
        self.assertEqual(len({row['operation_id'] for row in history['items']}),50)
    async def test_history_pages_past_ten_thousand(self):
        # Synthetic retained rows exercise pagination, not connected execution.
        with self.store.connect() as db:
            for n in range(10051):
                body = self.change(operation_id=f.identity(100+n), expected_revision=n)
                db.execute('INSERT INTO l19_work_operations VALUES (?,?,?,?,?,?)',
                    (str(body.operation_id), str(body.subject_id), str(body.actor_id),
                     str(body.organization_id), body.model_dump_json(), '{}'))
        page = await self.store.history(self.body.subject_id, f.identity(4), f.identity(5),
                                        f.NOW, 10000)
        self.assertEqual(page['total'], 10051)
        self.assertEqual(len(page['items']), 50)
        self.assertEqual(page['next_offset'], 10050)
        last = await self.store.history(self.body.subject_id, f.identity(4), f.identity(5),
                                        f.NOW, page['next_offset'])
        self.assertEqual(last['total'], 10051)
        self.assertEqual([row['operation_id'] for row in last['items']],
                         [str(f.identity(10150))])
        self.assertIsNone(last['next_offset'])
        beyond = await self.store.history(self.body.subject_id, f.identity(4), f.identity(5),
                                          f.NOW, 10**100)
        self.assertEqual(beyond['items'], [])
        self.assertIsNone(beyond['next_offset'])
        for offset in (-1, True, 1.5):
            with self.assertRaisesRegex(s.Rejected, 'invalid_page'):
                await self.store.history(self.body.subject_id, f.identity(4), f.identity(5),
                                         f.NOW, offset)

    async def test_adapter_current_scope_and_pending(self):
        import sys
        import types
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        package=types.ModuleType('work_adapter')
        package.__path__=[str(ROOT/'services/service-operations/modules/authorized-work')]
        sys.modules['work_adapter']=package
        sys.modules['work_adapter.store']=s
        routes=load('work_adapter.routes','services/service-operations/modules/authorized-work/routes.py')
        async def scope():
            return types.SimpleNamespace(actor_id=f.identity(4),organization_id=f.identity(5))
        app=FastAPI()
        app.include_router(routes.create_router(self.store,scope,lambda:f.NOW))
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            base='/internal/v1/authorized-work'
            self.assertEqual((await client.get(f'{base}/subjects/{self.body.subject_id}')).status_code,200)
            self.assertEqual((await client.post(f'{base}/commands',json={'note':'invalid'})).status_code,422)
            response=await client.post(f'{base}/commands',json=json.loads(self.body.model_dump_json()))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['source_revision'],1)
            incident=self.change(operation_id=f.identity(8),expected_revision=1,kind='damage',line_ids=[],readings=[])
            self.provider.timeout=True
            response=await client.post(f'{base}/commands',json=json.loads(incident.model_dump_json()))
            self.assertEqual(response.json()['state'],'pending')
            self.assertEqual((await client.get(f'{base}/operations/{incident.operation_id}')).json()['state'],'pending')
            self.assertEqual((await client.get(f'{base}/subjects/{self.body.subject_id}/observations')).json()['total'],2)
            self.provider.auth['state']='denied'
            self.assertEqual((await client.get(f'{base}/operations/{incident.operation_id}')).status_code,403)
            self.assertEqual((await client.post(f'{base}/commands',json=json.loads(incident.model_dump_json()))).status_code,403)
    def test_strict_producer_boolean(self):
        with self.assertRaises(ValueError):
            c.Authority(**{**f.authority(),'custody_current':1})

    async def test_responsible_person_rejection_is_durable_and_correctable(self):
        wrong = self.change(next_actor=f.identity(99))
        for restart in (False, True):
            if restart:
                self.store = s.Store(self.path, self.provider, c)
            with self.assertRaises(s.Rejected) as failure:
                await self.run_command(wrong)
            self.assertEqual(str(failure.exception), 'responsible_actor')
            self.assertTrue(failure.exception.not_applied)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_operations').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_rejections').fetchone()[0], 1)
        with self.assertRaisesRegex(s.Rejected, 'duplicate_conflict'):
            await self.run_command()
        corrected = self.change(operation_id=f.identity(91))
        self.assertEqual((await self.run_command(corrected))['state'], 'recorded')

    async def test_declined_custodian_incidents_use_current_read_permission(self):
        self.provider.auth.update(state='declined', payment_state='unpaid')
        async def execution_denied(*args):
            raise PermissionError()
        self.provider.authorize = execution_denied
        for index, kind in enumerate(('loss', 'damage')):
            body = self.change(operation_id=f.identity(3000+index), expected_revision=index,
                               kind=kind, line_ids=[], readings=[])
            result = await self.run_command(body)
            self.assertEqual(result['state'], 'paused')
            self.assertEqual(result['hold_revision'], 2)
            self.assertFalse(result['release_eligible'])
        self.assertEqual(len(self.provider.holds), 2)
        with self.assertRaisesRegex(s.Rejected, 'unavailable'):
            await self.run_command(self.change(operation_id=f.identity(3010), expected_revision=2))

    async def test_pending_payment_incidents_reconcile_after_restart(self):
        self.provider.auth['payment_state'] = 'pending'
        with self.assertRaisesRegex(s.Rejected, 'denied'):
            await self.run_command()
        for index, kind in enumerate(('loss', 'damage')):
            body = self.change(operation_id=f.identity(4000+index), expected_revision=index,
                               kind=kind, line_ids=[], readings=[])
            self.provider.timeout = True
            result = await self.run_command(body)
            self.assertEqual(result['state'], 'pending')
            self.store = s.Store(self.path, self.provider, c)
            self.assertEqual(await self.store.lookup(body.operation_id, f.identity(4),
                                                    f.identity(5), f.NOW), result)
            self.provider.timeout = False
            held = await self.run_command(body)
            self.assertEqual(held['state'], 'paused')
            self.assertEqual(held['hold_revision'], 2)
            self.assertFalse(held['release_eligible'])
            self.assertEqual(await self.run_command(body), held)
        self.assertEqual(self.provider.holds, [f.identity(4000), f.identity(4000),
                                              f.identity(4001), f.identity(4001)])
        with self.assertRaisesRegex(s.Rejected, 'denied'):
            await self.run_command(self.change(operation_id=f.identity(4010), expected_revision=2))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_operations').fetchone()[0], 2)

    async def test_custody_incidents_fail_closed_on_current_scope(self):
        for changes in ({'state':'denied'}, {'custody_current':False},
                        {'organization_id':f.identity(99)}, {'watch_id':f.identity(99)},
                        {'valid_until':f.NOW}):
            with self.subTest(changes=changes):
                self.provider.auth = {**f.authority(), **changes}
                with self.assertRaises(s.Rejected):
                    await self.run_command(self.change(kind='loss', line_ids=[], readings=[]))
        self.assertEqual(self.provider.holds, [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_operations').fetchone()[0], 0)

    async def test_retained_incident_reconciles_after_revision_changes(self):
        for index, kind in enumerate(('loss', 'damage', 'material_change')):
            self.provider.auth = f.authority()
            body = self.change(operation_id=f.identity(5000+index), expected_revision=index,
                               kind=kind, line_ids=[], readings=[])
            self.provider.timeout = True
            pending = await self.run_command(body)
            self.store = s.Store(self.path, self.provider, c)
            self.provider.auth.update(source_revision=2, quote_id=f.identity(90),
                                      quote_revision=3, policy_revision=4)
            self.provider.timeout = False
            self.provider.auth['state'] = 'denied'
            with self.assertRaisesRegex(s.Rejected, 'denied'):
                await self.run_command(body)
            self.assertEqual(len(self.provider.holds), index*2+1)
            self.provider.auth['state'] = 'authorized'
            with self.assertRaisesRegex(s.Rejected, 'duplicate_conflict'):
                await self.run_command(c.Command(**{**body.model_dump(), 'note':'Changed'}))
            held = await self.run_command(body)
            self.assertEqual(held['state'], 'paused')
            self.assertEqual(held['revision'], pending['revision'])
            self.assertEqual(held['source_revision'], 1)
            self.assertEqual(held['quote_id'], str(body.quote_id))
            self.assertEqual(await self.run_command(body), held)
            self.assertEqual(self.provider.holds[-2:], [body.operation_id]*2)

    async def test_lost_progress_response_lookup_after_source_changes(self):
        recorded = await self.run_command()
        self.provider.auth['source_revision'] = 2
        self.store = s.Store(self.path, self.provider, c)
        with self.assertRaises(s.Rejected) as failure:
            await self.run_command()
        self.assertEqual(str(failure.exception), 'stale')
        self.assertFalse(failure.exception.not_applied)
        recovered = await self.store.lookup(self.body.operation_id, f.identity(4),
                                            f.identity(5), f.NOW)
        self.assertEqual(recovered, recorded)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_operations').fetchone()[0], 1)

    async def test_paused_progress_rejection_survives_restart_and_allows_incident(self):
        damage = self.change(kind='damage', line_ids=[], readings=[])
        await self.run_command(damage)
        progress = self.change(operation_id=f.identity(6000), expected_revision=1)
        for restart in (False, True):
            if restart:
                self.store = s.Store(self.path, self.provider, c)
            with self.assertRaises(s.Rejected) as failure:
                await self.run_command(progress)
            self.assertEqual(str(failure.exception), 'paused')
            self.assertTrue(failure.exception.not_applied)
        with self.assertRaisesRegex(s.Rejected, 'duplicate_conflict'):
            await self.run_command(c.Command(**{**progress.model_dump(), 'kind':'loss',
                                               'line_ids':[], 'readings':[]}))
        incident = self.change(operation_id=f.identity(6001), expected_revision=1,
                               kind='loss', line_ids=[], readings=[])
        self.assertEqual((await self.run_command(incident))['state'], 'paused')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_rejections').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM l19_work_operations').fetchone()[0], 2)


    async def test_delayed_preparation_preserves_actual_reading_times_and_retry(self):
        loaded = await self.store.context(self.body.subject_id, f.identity(4), f.identity(5), f.NOW)
        now = f.NOW + timedelta(minutes=70)
        fresh = await self.store.context(self.body.subject_id, f.identity(4), f.identity(5), now)
        self.assertNotEqual(loaded['server_now'], fresh['server_now'])
        body = self.change(observed_at=now, next_review_at=now+timedelta(hours=1),
            readings=[
                dict(phase='before', observed_at=f.NOW+timedelta(minutes=30),
                     seconds_per_day=12, method='Synthetic timing instrument'),
                dict(phase='after', observed_at=f.NOW+timedelta(minutes=65),
                     seconds_per_day=2, method='Synthetic timing instrument')])
        result = await self.run_command(body, now)
        self.assertEqual(result['state'], 'recorded')
        self.store = s.Store(self.path, self.provider, c)
        self.assertEqual(await self.run_command(body, now+timedelta(minutes=5)), result)
        history = await self.store.history(body.subject_id, f.identity(4), f.identity(5), now)
        self.assertEqual(history['items'][0], json.loads(body.model_dump_json()))
        self.assertEqual(result['next_review_at'], (now+timedelta(hours=1)).isoformat())
