import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / 'packages/contracts-service/finish'
MODULE = ROOT / 'services/service-operations/modules/finish-consent'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

for name in ('bt_contracts', 'bt_contracts.service', 'bt_contracts.service.finish'):
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
contract = load('bt_contracts.service.finish.v1', CONTRACT / 'v1.py')
package = types.ModuleType('finish_package')
package.__path__ = [str(MODULE)]
sys.modules['finish_package'] = package
service = load('finish_package.service', MODULE / 'service.py')
routes = load('finish_package.routes', MODULE / 'routes.py')

class Provider:
    def __init__(self, source):
        self.source = source
        self.unavailable = False

    @contextmanager
    def current(self, actor, subject, timeout):
        assert timeout == 2.0
        if self.unavailable:
            raise TimeoutError()
        yield self.source

class FinishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'consent.sqlite'
        self.db = sqlite3.connect(self.path)
        self.db.executescript((MODULE / 'migrations/L17_0001_finish.sql').read_text())
        self.source = contract.Snapshot.model_validate_json((CONTRACT / 'fixtures/source.json').read_text())
        self.command = contract.Command.model_validate_json((CONTRACT / 'fixtures/command.json').read_text())
        self.provider = Provider(self.source)
        self.now = self.source.valid_until - timedelta(seconds=1)
        self.subject = service.ConsentService(self.db, self.provider, lambda: self.now)
        self.actor = self.command.actor_id

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def reject(self, code, command=None):
        with self.assertRaises(service.Refusal) as caught:
            self.subject.submit(self.actor, command or self.command)
        self.assertEqual(caught.exception.code, code)

    def test_success_restart_duplicate_and_outbox(self):
        result = self.subject.submit(self.actor, self.command)
        self.assertEqual(result, json.loads((CONTRACT / 'fixtures/success.json').read_text()))
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.subject = service.ConsentService(self.db, self.provider, lambda: self.now)
        self.assertEqual(self.subject.submit(self.actor, self.command), result)
        self.assertEqual(self.subject.lookup(self.actor, self.command.subject_id, self.command.operation_id), result)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM finish_outbox').fetchone()[0], 1)
        payload = self.db.execute('SELECT payload FROM finish_outbox').fetchone()[0]
        self.assertNotIn('preservation', payload)
        self.assertNotIn('choices', payload)

    def test_before_equal_after(self):
        self.assertEqual(self.subject.submit(self.actor, self.command)['state'], 'recorded')
        for delta in (0, 1):
            self.now = self.source.valid_until + timedelta(seconds=delta)
            self.reject('stale')

    def test_duplicate_rechecks_boundary_after_lock(self):
        self.subject.submit(self.actor, self.command)
        for delta in (-1, 0, 1):
            with self.subTest(delta=delta):
                times = iter([self.now, self.source.valid_until + timedelta(seconds=delta)])
                self.subject.clock = lambda: next(times)
                if delta < 0:
                    self.assertEqual(self.subject.submit(self.actor, self.command)['state'], 'recorded')
                else:
                    self.reject('stale')
                self.assertFalse(self.db.in_transaction)
                for table in ('finish_consents', 'finish_receipts', 'finish_outbox'):
                    self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 1)

    def test_denied_and_stale_fixtures(self):
        for name, code in [('denied', 'denied'), ('stale', 'stale')]:
            self.provider.source = contract.Snapshot.model_validate_json((CONTRACT / f'fixtures/{name}.json').read_text())
            self.reject(code)

    def test_cross_account_business_watch_and_bindings(self):
        self.reject('denied', self.command.model_copy(update={'actor_id': uuid4()}))
        for field in ('organization_id', 'watch_id', 'subject_id', 'quote_id'):
            self.reject('stale', self.command.model_copy(update={field: uuid4()}))
        for field in ('source_revision', 'assessment_revision', 'quote_revision', 'policy_revision', 'expected_revision'):
            self.reject('stale', self.command.model_copy(update={field: 9}))

    def test_limits_require_no_polish(self):
        for field, values in {'original':['unknown'], 'coating':['present','unknown'], 'plating':['thin','present','unknown'], 'engraving':['present','unknown'], 'suitable':[False], 'material_known':[False], 'preservation_assessed':[False], 'desired':['mirror','preserve']}.items():
            for value in values:
                area = self.source.areas[0].model_copy(update={field:value})
                self.provider.source = self.source.model_copy(update={'areas':(area,)})
                self.reject('unsuitable')
        choice = self.command.choices[0].model_copy(update={'decision':'no_polish'})
        self.assertEqual(self.subject.submit(self.actor, self.command.model_copy(update={'choices':(choice,)}))['state'], 'recorded')

    def test_unknown_expanded_and_duplicate_areas(self):
        choice = self.command.choices[0].model_copy(update={'area_id':uuid4()})
        self.reject('scope_mismatch', self.command.model_copy(update={'choices':(choice,)}))
        data = self.command.model_dump()
        data['choices'] = data['choices'] * 2
        with self.assertRaises(ValueError):
            contract.Command.model_validate(data)
        self.provider.source = self.source.model_copy(update={'areas':(*self.source.areas,self.source.areas[0].model_copy(update={'area_id':uuid4()}))})
        self.reject('scope_mismatch')

    def test_uncertain_retry_conflict_and_revocation(self):
        self.provider.unavailable = True
        result = self.subject.submit(self.actor, self.command)
        self.assertEqual(result, json.loads((CONTRACT / 'fixtures/lost-response.json').read_text()))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM finish_receipts').fetchone()[0], 0)
        self.provider.unavailable = False
        self.subject.submit(self.actor, self.command)
        choice = self.command.choices[0].model_copy(update={'decision':'no_polish'})
        self.reject('conflict', self.command.model_copy(update={'choices':(choice,)}))
        self.provider.source = self.source.model_copy(update={'current':False})
        self.reject('denied')
        with self.assertRaises(service.Refusal):
            self.subject.lookup(self.actor, self.command.subject_id, self.command.operation_id)

    def test_current_detail_and_immutable_history(self):
        self.subject.submit(self.actor, self.command)
        self.assertEqual(len(self.subject.detail(self.actor, self.command.subject_id)['choices']), 1)
        self.provider.source = self.source.model_copy(update={'quote_revision':2})
        self.assertEqual(self.subject.detail(self.actor, self.command.subject_id)['choices'], [])
        revised = self.command.model_copy(update={'quote_revision':2, 'expected_revision':1, 'operation_id':uuid4()})
        self.subject.submit(self.actor, revised)
        snapshots = self.db.execute('SELECT source_snapshot FROM finish_receipts ORDER BY rowid').fetchall()
        self.assertEqual([json.loads(row[0])['quote_revision'] for row in snapshots], [1, 2])

    def test_expiry_during_transaction_rolls_back(self):
        times = iter([self.now, self.source.valid_until])
        self.subject.clock = lambda: next(times)
        self.reject('stale')
        for table in ('finish_consents', 'finish_receipts', 'finish_outbox'):
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_route_adapter_bounds_identity_and_errors(self):
        import asyncio
        from fastapi import HTTPException
        from starlette.requests import Request
        class Adapter:
            def submit(inner, actor, command):
                if actor != command.actor_id:
                    raise service.Refusal('denied')
                return service.ConsentService._result(command, 1, 'recorded')

            def lookup(inner, actor, subject, operation):
                raise service.Refusal('not_found')

            def detail(inner, actor, subject):
                raise service.Refusal('unavailable')
        @contextmanager
        def factory():
            yield Adapter()
        router = routes.create_router(factory, lambda: self.actor)
        detail, submit, lookup = [route.endpoint for route in router.routes]
        self.assertEqual(submit(self.command, self.actor)['state'], 'recorded')
        for call, status in [(lambda: submit(self.command, uuid4()), 403),
                             (lambda: detail(self.command.subject_id, self.actor), 503),
                             (lambda: lookup(self.command.subject_id, self.command.operation_id, self.actor), 404)]:
            with self.assertRaises(HTTPException) as caught:
                call()
            self.assertEqual(caught.exception.status_code, status)
        async def oversized():
            async def receive():
                return {'type':'http.request', 'body':b'x'*32769, 'more_body':False}
            request = Request({'type':'http', 'method':'POST', 'path':'/v1/finish/consents', 'headers':[]}, receive)
            with self.assertRaises(HTTPException) as caught:
                await router.routes[1].get_route_handler()(request)
            self.assertEqual(caught.exception.status_code, 413)
        asyncio.run(oversized())

    def test_lost_response_with_changed_source_resolves_original_receipt(self):
        recorded = self.subject.submit(self.actor, self.command)
        self.provider.source = self.source.model_copy(update={'source_revision': 2})
        self.reject('stale')
        self.assertEqual(self.subject.lookup(self.actor, self.command.subject_id, self.command.operation_id), recorded)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM finish_receipts').fetchone()[0], 1)

    def test_retained_terms_required_and_preserved(self):
        for field in ('fee_en', 'fee_ar', 'return_en', 'return_ar', 'assurance_en', 'assurance_ar', 'support_path'):
            data = self.source.model_dump()
            data['terms'][field] = ''
            with self.assertRaises(ValueError):
                contract.Snapshot.model_validate(data)
        self.subject.submit(self.actor, self.command)
        stored = json.loads(self.db.execute('SELECT source_snapshot FROM finish_receipts').fetchone()[0])
        self.assertEqual(stored['terms'], self.source.terms.model_dump())

    def test_schema_bounds(self):
        for field, value in [('total_minor',1.5),('total_minor',True),('total_minor',float('inf')),('currency','LBP'),('valid_until','2026-11-17T00:00:00')]:
            data = self.source.model_dump()
            data[field] = value
            with self.assertRaises(ValueError):
                contract.Snapshot.model_validate(data)

if __name__ == '__main__':
    unittest.main()
