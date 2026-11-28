import asyncio
from dataclasses import replace, asdict
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

contract = load('brand_contract', 'packages/contracts-orders/brand-jobs/contract.py')
service = load('brand_service', 'services/orders/modules/brand-jobs/service.py')
adapter = load('brand_adapter', 'services/orders/modules/brand-jobs/service_adapter.py')

class Provider:
    def __init__(self):
        self.scope = contract.Scope('buyer', 'watch', 'brand', 1, 'quote', 1, 1, 'USD', 500000, 25000,
                                    True, True, True, True, True, True, True, 'worker', True,
                                    'assessor', 'approver', 'quality', 'reviewer', 1, 'order')
        self.effects = {}
        self.lost = False
        self.allowed = True
    async def check_access(self, command):
        if not self.allowed:
            raise PermissionError('denied')
    async def current_scope(self, command):
        return self.scope
    async def lookup_operation(self, command):
        return self.effects.get(command.operation_id)
    async def assign_recovery(self, command):
        return dict(operator_id='operator-7', next_action='reconcile_current_authority',
                    escalation_actor_id='operator-8', opened_at='2026-11-16T12:00:00+00:00')
    async def authorize_once(self, command, scope):
        result = self.effects.setdefault(command.operation_id, {'state': 'authorized', 'job_id': 'job', 'assignee_id': scope.assignee_id, 'binding': asdict(command), 'source_revision': scope.source_revision})
        if self.lost:
            self.lost = False
            raise TimeoutError()
        return result

class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'receipts.db')
        self.provider = Provider()
        self.coordinator = service.Coordinator(self.path, self.provider)
        self.command = contract.Command('operation', 'buyer', 'watch', 'buyer', 'brand', 1, 'quote', 1, 1)
    def tearDown(self):
        self.coordinator.close()
        self.tmp.cleanup()
    def run_command(self):
        return asyncio.run(self.coordinator.authorize(self.command))
    def test_authorized_duplicate(self):
        self.assertEqual(self.run_command()['state'], 'authorized')
        self.assertEqual(self.run_command()['job_id'], 'job')
        self.assertEqual(len(self.provider.effects), 1)
    def test_missing_prerequisites(self):
        for field in ('paid_held', 'allocation_current', 'grant_current', 'authority_current', 'assignee_qualified', 'consent_current', 'accepted'):
            with self.subTest(field=field):
                original = self.provider.scope
                self.provider.scope = replace(original, **{field: False})
                self.assertEqual(self.run_command()['state'], 'pending')
                self.assertFalse(self.provider.effects)
                self.provider.scope = original
    def test_stale_and_cross_account(self):
        for changes, expected in (({'revision': 2}, 'stale'), ({'buyer_id': 'other'}, 'denied'), ({'watch_id': 'other'}, 'denied')):
            self.provider.scope = replace(Provider().scope, **changes)
            self.assertEqual(self.run_command()['state'], expected)
    def test_lost_response_restart(self):
        self.provider.lost = True
        self.assertEqual(self.run_command()['state'], 'pending')
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        self.assertEqual(self.run_command()['state'], 'authorized')
        self.assertEqual(len(self.provider.effects), 1)
    def test_conflict_and_revoked_read(self):
        self.run_command()
        with self.assertRaises(ValueError):
            asyncio.run(self.coordinator.authorize(replace(self.command, quote_revision=2)))
        self.provider.allowed = False
        with self.assertRaises(PermissionError):
            asyncio.run(self.coordinator.lookup(self.command))
    def test_repair_without_customization_approval(self):
        self.provider.scope = replace(self.provider.scope, approval_current=False, grant_current=False, consent_current=False,
                                      service_acceptance_id='acceptance', payment_operation_id='payment', payment_revision=1)
        acceptance = contract.ServiceAcceptance('acceptance', 1, 'buyer', 'brand', 'watch', 'quote', 1, 500000, True)
        payment = contract.PaidServiceScope('buyer', 'order', 'service', 'watch', 'quote', 1, 'USD', 500000, 'payment', 1, 'paid_held')
        result = asyncio.run(adapter.authorize_service(self.coordinator, self.command, acceptance, payment))
        self.assertEqual(result['state'], 'authorized')
    def test_unpaid_repair_recovers_with_same_binding_after_restart(self):
        acceptance = contract.ServiceAcceptance('acceptance', 1, 'buyer', 'brand', 'watch', 'quote', 1, 500000, True)
        payment = contract.PaidServiceScope('buyer', 'order', 'service', 'watch', 'quote', 1, 'USD', 500000, 'payment', 1, 'unpaid')
        self.provider.scope = replace(self.provider.scope, approval_current=False, grant_current=False,
                                      consent_current=False, paid_held=False, service_acceptance_id='acceptance')
        first = asyncio.run(adapter.authorize_service(self.coordinator, self.command, acceptance, payment))
        self.assertEqual(first['state'], 'pending')
        self.assertFalse(self.provider.effects)
        bound = adapter.repair_binding(self.command, acceptance)
        self.assertEqual(asyncio.run(self.coordinator.lookup(bound))['state'], 'pending')
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        self.provider.scope = replace(self.provider.scope, paid_held=True,
                                      payment_operation_id='confirmed-payment', payment_revision=2)
        payment = replace(payment, state='paid_held', payment_operation_id='confirmed-payment', payment_revision=2)
        second = asyncio.run(adapter.authorize_service(self.coordinator, self.command, acceptance, payment))
        self.assertEqual((second['state'], second['operation_id']), ('authorized', first['operation_id']))
        self.assertEqual(asyncio.run(self.coordinator.lookup(bound))['job_id'], second['job_id'])
        asyncio.run(adapter.authorize_service(self.coordinator, self.command, acceptance, payment))
        self.assertEqual(len(self.provider.effects), 1)
        with self.assertRaises(ValueError):
            asyncio.run(adapter.authorize_service(self.coordinator, self.command,
                        replace(acceptance, acceptance_id='changed'), payment))

    def test_revocation_after_success(self):
        self.run_command()
        self.provider.scope = replace(self.provider.scope, grant_current=False)
        self.assertEqual(self.run_command()['state'], 'pending')
        self.assertEqual(asyncio.run(self.coordinator.lookup(self.command))['state'], 'pending')
    def test_replaced_assignee_holds_lookup(self):
        self.run_command()
        self.provider.scope = replace(self.provider.scope, assignee_id='replacement')
        first = asyncio.run(self.coordinator.lookup(self.command))
        second = asyncio.run(self.coordinator.lookup(self.command))
        self.assertEqual(first['state'], 'pending')
        self.assertEqual(first['next_review_at'], second['next_review_at'])

    def test_lookup_recovers_lost_response_after_restart(self):
        self.provider.lost = True
        self.assertEqual(self.run_command()['state'], 'pending')
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        result = asyncio.run(self.coordinator.lookup(self.command))
        self.assertEqual((result['state'], result['assignee_id']), ('authorized', 'worker'))
        self.assertEqual(len(self.provider.effects), 1)

    def test_changed_assignment_cannot_relabel_original_job(self):
        self.run_command()
        self.provider.scope = replace(self.provider.scope, assignee_id='replacement')
        self.assertEqual(asyncio.run(self.coordinator.lookup(self.command))['state'], 'pending')
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        for _ in range(2):
            result = self.run_command()
            self.assertEqual(result['pending_reason'], 'assignment_changed')
            self.assertNotIn('job_id', result)
        self.assertEqual(self.provider.effects['operation']['assignee_id'], 'worker')

    def test_recovery_assignment_and_deadlines_survive_restart(self):
        self.provider.scope = replace(self.provider.scope, paid_held=False)
        first = self.run_command()
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        second = asyncio.run(self.coordinator.lookup(self.command))
        self.assertEqual(first['recovery'], second['recovery'])
        self.assertEqual(second['next_actor'], 'operator-7')
        self.assertEqual(second['next_review_at'], '2026-11-17T12:00:00+00:00')
        self.assertEqual(second['recovery']['escalate_at'], '2026-11-18T12:00:00+00:00')

    def test_unknown_fact_and_stable_review(self):
        self.provider.scope = replace(self.provider.scope, paid_held='unknown')
        first = self.run_command()
        second = self.run_command()
        self.assertEqual(first['state'], 'pending')
        self.assertEqual(first['next_review_at'], second['next_review_at'])
    def test_money_and_independence(self):
        for changes in ({'total_minor': True}, {'business_fee_minor': 50000}, {'currency': 'other'}, {'quality_reviewer_id': 'assessor'}):
            self.provider.scope = replace(Provider().scope, **changes)
            self.assertIn(self.run_command()['state'], ('denied', 'pending'))


release = load('brand_release', 'services/orders/modules/brand-jobs/release.py')

class ReleaseTests(unittest.TestCase):
    def test_actual_quality_receipt_window_and_holds(self):
        from datetime import datetime, timedelta, timezone
        received = datetime(2026, 11, 1, tzinfo=timezone.utc)
        facts = release.ReleaseFacts('job', 'watch', 1, 1, 1, 1, 'quality', 'assessor', 'approver',
                                     True, True, True, True, True, 'job', 'watch', True, True,
                                     received, True, True, True)
        end = received + timedelta(hours=168)
        self.assertFalse(release.release_ready(facts, end - timedelta(microseconds=1)))
        self.assertTrue(release.release_ready(facts, end))
        self.assertTrue(release.release_ready(facts, end + timedelta(microseconds=1)))
        for field in ('quality_assignment_current', 'quality_passed', 'tests_recorded', 'fit_recorded',
                      'returned_parts_recorded', 'receipt_actual', 'authorized_recipient',
                      'dispute_clear', 'incident_clear', 'holds_clear'):
            with self.subTest(field=field):
                self.assertFalse(release.release_ready(replace(facts, **{field: False}), end))
        for changes in ({'received_at': None}, {'receipt_watch_id': 'other'}, {'quality_work_revision': 2},
                        {'quality_reviewer_id': 'assessor'}):
            self.assertFalse(release.release_ready(replace(facts, **changes), end))

routes = load('brand_routes', 'services/orders/modules/brand-jobs/routes.py')

class RouteTests(unittest.TestCase):
    setUp = AuthorizationTests.setUp
    tearDown = AuthorizationTests.tearDown
    def test_missing_scope_is_unavailable_and_command_recovers(self):
        scope = self.provider.scope
        for missing in (None, object()):
            self.provider.scope = missing
            for route in (routes.authorize_route, routes.lookup_route):
                code, result = asyncio.run(route(self.coordinator, self.command))
                self.assertEqual((code, result['state'], result['operation_id']),
                                 (503, 'unavailable', self.command.operation_id))
                self.assertEqual(result['pending_reason'], 'current_scope_unavailable')
                self.assertEqual(result['next_actor'], 'operator-7')
                self.assertNotIn('job_id', result)
            self.assertFalse(self.provider.effects)
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        self.provider.scope = scope
        code, result = asyncio.run(routes.authorize_route(self.coordinator, self.command))
        self.assertEqual((code, result['state']), (200, 'authorized'))
        self.assertEqual(len(self.provider.effects), 1)

    def test_missing_scope_hides_outcome_until_lookup_recovers(self):
        code, original = asyncio.run(routes.authorize_route(self.coordinator, self.command))
        self.assertEqual(code, 200)
        scope = self.provider.scope
        self.provider.scope = None
        for route in (routes.authorize_route, routes.lookup_route):
            code, result = asyncio.run(route(self.coordinator, self.command))
            self.assertEqual((code, result['state']), (503, 'unavailable'))
            self.assertEqual(result['operation_id'], original['operation_id'])
            self.assertNotIn('job_id', result)
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        self.provider.scope = scope
        code, result = asyncio.run(routes.lookup_route(self.coordinator, self.command))
        self.assertEqual((code, result['job_id']), (200, original['job_id']))
        self.assertEqual(len(self.provider.effects), 1)

    def test_initial_access_outages_are_unavailable_and_recover(self):
        original = self.provider.check_access
        for failure in (TimeoutError, ConnectionError):
            async def unavailable(command):
                raise failure()
            self.provider.check_access = unavailable
            code, result = asyncio.run(routes.authorize_route(self.coordinator, self.command))
            self.assertEqual((code, result['state'], result['operation_id']),
                             (503, 'unavailable', self.command.operation_id))
            self.assertFalse(self.provider.effects)
            self.provider.check_access = original
        code, result = asyncio.run(routes.authorize_route(self.coordinator, self.command))
        self.assertEqual((code, result['state']), (200, 'authorized'))
        self.assertEqual(len(self.provider.effects), 1)

    def test_invalid_recovery_is_unavailable_with_stable_binding(self):
        self.provider.scope = replace(self.provider.scope, paid_held=False)
        original = self.provider.assign_recovery
        for assignment in ({}, None, {'operator_id': 'operator'},
                           dict(operator_id='operator', next_action='review',
                                escalation_actor_id='escalation', opened_at='invalid'),
                           dict(operator_id='operator', next_action='review',
                                escalation_actor_id='escalation', opened_at='2026-11-16T12:00:00')):
            async def missing(command):
                return assignment
            self.provider.assign_recovery = missing
            for route in (routes.authorize_route, routes.lookup_route):
                code, result = asyncio.run(route(self.coordinator, self.command))
                self.assertEqual((code, result['state'], result['operation_id']),
                                 (503, 'unavailable', self.command.operation_id))
                self.assertEqual(result['pending_reason'], 'recovery_assignment_unavailable')
                self.assertNotIn('recovery', result)
            self.assertFalse(self.provider.effects)
        code, _ = asyncio.run(routes.authorize_route(
            self.coordinator, replace(self.command, quote_revision=2)))
        self.assertEqual(code, 409)
        self.coordinator.close()
        self.coordinator = service.Coordinator(self.path, self.provider)
        self.provider.assign_recovery = original
        code, result = asyncio.run(routes.lookup_route(self.coordinator, self.command))
        self.assertEqual((code, result['state']), (202, 'pending'))
        self.assertEqual(result['next_actor'], 'operator-7')

    def test_route_statuses(self):
        self.provider.scope = replace(self.provider.scope, paid_held=False)
        code, result = asyncio.run(routes.authorize_route(self.coordinator, self.command))
        self.assertEqual((code, result['state']), (202, 'pending'))
        self.provider.allowed = False
        code, result = asyncio.run(routes.lookup_route(self.coordinator, self.command))
        self.assertEqual(code, 403)
        self.assertEqual(set(result['message']), {'en', 'ar'})

if __name__ == '__main__':
    unittest.main()
