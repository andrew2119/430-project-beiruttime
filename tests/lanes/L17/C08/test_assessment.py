import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Command = load('assessment_contract', 'packages/contracts-service/brand-assessment/v1.py').Command
service = load('assessment_service', 'services/service-operations/modules/brand-assessment/service.py')


class Journey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'records.db')
        self.facts = dict(active=True, technical=True, official_brand=True, organization_id='brand',
                          actor_id='staff', subject_id='request', brand_id='brand', approver_id='approver', quality_reviewer_id='quality', request_state='submitted', base_id='base', caliber_id='caliber', option_snapshots=[dict(dimension=d, option_id=d+'-option', option_revision=1) for d in ['color_finish', 'material_grade', 'movement', 'dial_hands_markers', 'finishing_package']], request_revision=1, watch_id='watch', capability_revision=1)
        self.store = service.Assessment(self.path, self.resolve, lambda *args: 'responsible-person')

    def resolve(self, actor, organization, subject):
        return {**self.facts, 'actor_id': actor}

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def command(self, **changes):
        return Command(**{**dict(schema_version='brand-assessment.v1', operation_id='operation-1',
            subject_id='request', watch_id='watch', actor_id='staff', organization_id='brand',
            expected_revision=0, request_revision=1, assignment_revision=0, capability_revision=1,
            kind='claim'), **changes})

    def test_restart_duplicate_and_conflict(self):
        c = self.command()
        result = self.store.command(c)
        self.store.db.close()
        self.store = service.Assessment(self.path, self.resolve, lambda *args: 'responsible-person')
        self.assertEqual(result, self.store.command(c))
        with self.assertRaises(service.Rejected):
            self.store.command(self.command(reason='changed'))

    def test_current_scope_and_revision(self):
        for change in ({'organization_id': 'other'}, {'request_revision': 2}, {'capability_revision': 2}):
            with self.assertRaises(service.Rejected):
                self.store.command(self.command(**change))
        self.facts['technical'] = False
        with self.assertRaises(service.Rejected):
            self.store.command(self.command())

    def test_old_assignee(self):
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='reassign', replacement_id='next', expected_revision=1, assignment_revision=1))
        receipt = self.store.command(self.command(operation_id='operation-2', kind='reassign', replacement_id='next', expected_revision=1, assignment_revision=1))
        self.assertEqual('next', receipt['claimant'])
        self.assertNotIn('limitations', receipt)
        with self.assertRaises(service.Rejected):
            self.store.lookup('staff', 'brand', 'request', 'operation-1')
        with self.assertRaises(service.Rejected):
            self.store.command(self.command())
        with self.assertRaises(service.Rejected):
            self.store.command(self.command(operation_id='operation-3', kind='assess', expected_revision=2, assignment_revision=2))

    def test_correction_preserves_history_and_blocks_stale(self):
        self.store.command(self.command())
        c = self.command(operation_id='operation-2', kind='correct', reason='Change material', expected_revision=1, assignment_revision=1)
        self.assertEqual('correction_pending', self.store.command(c)['state'])
        self.assertEqual('correction_pending', self.store.command(c)['state'])
        self.store.catalog_receipt('operation-2', 'request', 1, 2)
        self.store.catalog_receipt('operation-2', 'request', 1, 2)
        self.assertEqual(3, self.store.db.execute('SELECT count(*) FROM l17_history').fetchone()[0])
        recovered = self.store.lookup('staff', 'brand', 'request', 'operation-2')
        self.assertEqual('correction', recovered['state'])
        self.assertNotIn('reason', recovered)
        self.facts['request_revision'] = 2
        self.assertEqual('correction', self.store.read('staff', 'brand', 'request')['state'])
        self.assertNotIn('reason', self.store.read('staff', 'brand', 'request'))
        self.facts['request_revision'] = 2
        with self.assertRaises(service.Rejected):
            self.store.command(self.command(operation_id='operation-3', expected_revision=3, assignment_revision=2))

    def test_assessment_requires_actual_basis(self):
        self.store.command(self.command())
        with self.assertRaises(service.Rejected):
            self.store.command(self.command(operation_id='operation-2', kind='assess', expected_revision=1, assignment_revision=1))
        r = self.store.command(self.command(operation_id='operation-2', kind='assess', expected_revision=1,
            assignment_revision=1, feasibility='manual', limitations='Case fit requires measurement', lead_time_basis='Supplier confirmation required'))
        self.assertEqual('assessed', r['state'])

    def test_independence_and_wrong_subject(self):
        for change in ({'approver_id': 'staff'}, {'quality_reviewer_id': 'staff'}, {'subject_id': 'other'}, {'brand_id': 'other'}, {'option_snapshots': []}):
            old = dict(self.facts)
            self.facts.update(change)
            with self.assertRaises(service.Rejected):
                self.store.command(self.command())
            self.facts = old

    def test_routes_bind_authenticated_actor(self):
        from fastapi import FastAPI
        import asyncio
        import httpx
        from types import SimpleNamespace
        routes = load('assessment_routes', 'services/service-operations/modules/brand-assessment/routes.py')
        async def identity():
            return SimpleNamespace(actor_id='staff', organization_id='brand')
        app = FastAPI()
        app.include_router(routes.router_for(self.store, Command, identity))
        # Keep the local connection on the same thread as the request handler.
        original = self.store.command
        calls = []
        self.store.command = lambda body: calls.append(body) or {'state': 'claimed'}
        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
                response = await client.post('/v1/brand-assessments/request/commands', json=self.command(actor_id='other').model_dump())
                self.assertEqual(403, response.status_code)
                self.assertEqual([], calls)
                response = await client.post('/v1/brand-assessments/request/commands', json=self.command().model_dump())
                self.assertEqual(200, response.status_code)
        asyncio.run(exercise())
        self.store.command = original

    def test_delivery_timeout_then_matching_receipt(self):
        import asyncio
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        delivery = load('assessment_delivery', 'services/service-operations/modules/brand-assessment/delivery.py')
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='correct', reason='Revise finish', expected_revision=1, assignment_revision=1))

        class Catalog:
            fail = True
            operations = []

            async def request_correction(inner, body):
                inner.operations.append(body['operation_id'])
                if inner.fail:
                    raise TimeoutError()
                return dict(state='revised', operation_id=body['operation_id'], brand_id='brand', watch_id='watch', request_id='request', previous_revision=1, request_revision=2)

        catalog = Catalog()
        self.assertFalse(asyncio.run(delivery.deliver_one(self.store, catalog, now)))
        now += timedelta(minutes=1)
        catalog.fail = False
        self.assertTrue(asyncio.run(delivery.deliver_one(self.store, catalog, now)))
        self.assertFalse(asyncio.run(delivery.deliver_one(self.store, catalog, now)))
        self.assertEqual(['operation-2', 'operation-2'], catalog.operations)


    def test_revised_scope_requires_new_claim(self):
        self.store.command(self.command())
        self.facts['request_revision'] = 2
        current = self.store.read('staff', 'brand', 'request')
        self.assertEqual(1, current['request_revision'])
        self.assertEqual(2, current['current_request_revision'])
        self.assertEqual('revised', current['state'])
        self.assertNotIn('option_snapshots', current)
        with self.assertRaises(service.Rejected):
            self.store.command(self.command(operation_id='operation-2', kind='assess', request_revision=2, expected_revision=1, assignment_revision=1))
        r = self.store.command(self.command(operation_id='operation-2', kind='claim', request_revision=2, expected_revision=1, assignment_revision=1))
        self.assertEqual(2, r['assignment_revision'])

    def test_released_read_is_summary_only(self):
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='release', expected_revision=1, assignment_revision=1, reason='Private note'))
        self.assertNotIn('reason', self.store.read('next', 'brand', 'request'))
        with self.assertRaises(service.Rejected):
            self.store.lookup('staff', 'brand', 'request', 'operation-1')

    def test_capability_change_invalidates_assessment_identity(self):
        self.store.command(self.command())
        assessment = self.store.command(self.command(operation_id='operation-2', kind='assess', expected_revision=1,
            assignment_revision=1, feasibility='manual', limitations='Measurement needed', lead_time_basis='Parts check'))
        self.assertTrue(assessment['assessment_id'])
        self.facts['capability_revision'] = 2
        current = self.store.read('staff', 'brand', 'request')
        self.assertEqual('revised', current['state'])
        self.assertEqual(1, current['capability_revision'])
        self.assertEqual(2, current['current_capability_revision'])
        self.assertNotIn('assessment_id', current)
        claimed = self.store.command(self.command(operation_id='operation-3', expected_revision=2,
            assignment_revision=1, capability_revision=2))
        self.assertNotIn('assessment_id', claimed)

    def test_retry_boundary_and_durable_final_owner(self):
        import asyncio
        from datetime import datetime, timedelta, timezone
        delivery = load('assessment_delivery', 'services/service-operations/modules/brand-assessment/delivery.py')
        now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='correct', reason='Revise finish', expected_revision=1, assignment_revision=1))
        calls = []

        class Catalog:
            async def request_correction(inner, body):
                calls.append(body['operation_id'])
                raise TimeoutError()

        catalog = Catalog()
        asyncio.run(delivery.deliver_one(self.store, catalog, now))
        asyncio.run(delivery.deliver_one(self.store, catalog, now + timedelta(seconds=29, microseconds=999999)))
        self.assertEqual(1, len(calls))
        asyncio.run(delivery.deliver_one(self.store, catalog, now + timedelta(seconds=30)))
        self.assertEqual(2, len(calls))
        self.store.db.execute("UPDATE l17_outbox SET attempts=4,next_at=''")
        asyncio.run(delivery.deliver_one(self.store, catalog, now + timedelta(seconds=31)))
        self.store.db.close()
        self.store = service.Assessment(self.path, self.resolve, lambda *args: 'responsible-person')
        retained = self.store.lookup('staff', 'brand', 'request', 'operation-2')
        self.assertEqual('responsible-person', retained['next_actor'])
        self.assertEqual('responsible-person', retained['responsible_operator_id'])
        self.assertEqual('recover_catalog_receipt', retained['next_action'])
        self.assertTrue(retained['escalation_at'])
        self.assertEqual('catalog_unavailable', retained['pending_reason'])
        self.assertFalse(asyncio.run(delivery.deliver_one(self.store, catalog, now + timedelta(days=1))))

    def test_all_command_part_bounds(self):
        from pydantic import ValidationError
        for kind in ('claim', 'release', 'reassign', 'correct', 'assess'):
            self.command(kind=kind, parts=['p' * 300])
            for size in (0, 301, 1000000):
                with self.assertRaises(ValidationError):
                    self.command(kind=kind, parts=['p' * size])

    def test_followup_assignment_survives_restart(self):
        self.store.assign_followup = lambda business, subject, operation: 'responsible-person'
        self.store.command(self.command())
        c = self.command(operation_id='operation-2', kind='correct', reason='Revise finish', expected_revision=1, assignment_revision=1)
        first = self.store.command(c)
        self.assertEqual('responsible-person', first['responsible_operator_id'])
        self.assertEqual('recover_catalog_receipt', first['next_action'])
        from datetime import datetime, timedelta
        self.assertEqual(timedelta(hours=24), datetime.fromisoformat(first['escalation_at']) - datetime.fromisoformat(first['next_review_at']))
        self.store.db.close()
        self.store = service.Assessment(self.path, self.resolve, lambda *args: 'responsible-person')
        self.assertEqual(first, self.store.command(c))
        self.store.catalog_receipt('operation-2', 'request', 1, 2)
        record = __import__('json').loads(self.store.db.execute('SELECT body FROM l17_records').fetchone()[0])
        for key in ('responsible_operator_id', 'next_action', 'escalation_at'):
            self.assertNotIn(key, record)

    def test_recovery_redacts_changed_source_without_rewriting_history(self):
        self.store.command(self.command())
        command = self.command(operation_id='operation-2', kind='assess', expected_revision=1,
            assignment_revision=1, feasibility='manual', parts=['spring'],
            limitations='Private measurement', lead_time_basis='Supplier check')
        saved = self.store.command(command)
        import json
        for field in ('request_revision', 'capability_revision'):
            with self.subTest(field=field):
                self.facts[field] = 2
                for recovered in (self.store.read('staff', 'brand', 'request'),
                                  self.store.lookup('staff', 'brand', 'request', command.operation_id),
                                  self.store.command(command)):
                    self.assertEqual('revised', recovered['state'])
                    self.assertEqual(command.operation_id, recovered['operation_id'])
                    for private in ('assessment_id', 'assessment_revision', 'assessor_id',
                                    'feasibility', 'parts', 'limitations', 'lead_time_basis'):
                        self.assertNotIn(private, recovered)
                retained = json.loads(self.store.db.execute(
                    'SELECT body FROM l17_receipts WHERE operation=?', (command.operation_id,)).fetchone()[0])
                self.assertEqual(saved, retained)
                self.assertEqual(2, self.store.db.execute('SELECT count(*) FROM l17_history').fetchone()[0])
                self.facts[field] = 1

    def test_lookup_uses_one_current_authority_snapshot(self):
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='assess', expected_revision=1,
            assignment_revision=1, feasibility='manual', limitations='Measurement', lead_time_basis='Parts check'))
        calls = []

        def resolve(actor, organization, subject):
            calls.append(subject)
            return {**self.resolve(actor, organization, subject), 'request_revision': len(calls) + 1}

        self.store.resolve = resolve
        result = self.store.lookup('staff', 'brand', 'request', 'operation-2')
        self.assertEqual(['request'], calls)
        self.assertEqual('revised', result['state'])
        self.assertNotIn('assessment_id', result)

    def test_watch_change_requires_fresh_claim(self):
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='assess', expected_revision=1,
            assignment_revision=1, feasibility='manual', limitations='Measurement', lead_time_basis='Parts'))
        self.facts['watch_id'] = 'new-watch'
        current = self.store.read('staff', 'brand', 'request')
        self.assertEqual('revised', current['state'])
        self.assertNotIn('assessment_id', current)
        self.assertEqual('new-watch', current['current_watch_id'])
        with self.assertRaises(service.Rejected):
            self.store.command(self.command(operation_id='operation-3', kind='assess', watch_id='new-watch',
                expected_revision=2, assignment_revision=1, feasibility='manual', limitations='New', lead_time_basis='New'))
        claimed = self.store.command(self.command(operation_id='operation-3', watch_id='new-watch',
            expected_revision=2, assignment_revision=1))
        self.assertEqual(2, claimed['assignment_revision'])
        self.assertNotIn('assessment_id', claimed)

    def test_missing_followup_rolls_back_correction(self):
        self.store.command(self.command())
        for owner in (None, '', ' ' , 'x' * 101):
            self.store.assign_followup = lambda *args: owner
            with self.assertRaisesRegex(service.Rejected, 'unavailable'):
                self.store.command(self.command(operation_id='operation-2', kind='correct', reason='Revise',
                    expected_revision=1, assignment_revision=1))
            self.assertEqual('claimed', self.store.read('staff', 'brand', 'request')['state'])
            self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM l17_outbox').fetchone()[0])
            self.assertEqual(1, self.store.db.execute('SELECT count(*) FROM l17_receipts').fetchone()[0])

    def test_followup_timeout_is_unavailable_without_receipt(self):
        self.store.command(self.command())
        def unavailable(*args):
            raise TimeoutError()
        self.store.assign_followup = unavailable
        with self.assertRaisesRegex(service.Rejected, 'unavailable'):
            self.store.command(self.command(operation_id='operation-2', kind='correct', reason='Revise',
                expected_revision=1, assignment_revision=1))
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM l17_outbox').fetchone()[0])

    def test_concurrent_final_attempt_is_reserved_once(self):
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime, timezone
        from threading import Barrier
        delivery = load('assessment_delivery', 'services/service-operations/modules/brand-assessment/delivery.py')
        self.store.command(self.command())
        self.store.command(self.command(operation_id='operation-2', kind='correct', reason='Revise',
            expected_revision=1, assignment_revision=1))
        self.store.db.execute("UPDATE l17_outbox SET attempts=4,next_at=''")
        barrier = Barrier(2)
        calls = []

        class Catalog:
            async def request_correction(inner, body):
                calls.append(body['operation_id'])
                raise TimeoutError()

        def run():
            store = service.Assessment(self.path, self.resolve)
            statements = []
            store.db.set_trace_callback(statements.append)
            try:
                barrier.wait(timeout=5)
                asyncio.run(delivery.deliver_one(store, Catalog(), datetime(2026, 11, 17, tzinfo=timezone.utc)))
                self.assertTrue(statements[0].startswith('BEGIN IMMEDIATE'))
            finally:
                store.db.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(['operation-2'], calls)
        self.assertEqual(5, self.store.db.execute('SELECT attempts FROM l17_outbox').fetchone()[0])
