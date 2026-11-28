"""Focused contract checks; these results do not certify connected services."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest

from proof import (FIELDS, Observation, ROUTES, fixture, instant, minor,
                   payment_deadline, preparation_record, validate, verify_route)


class PreparationTests(unittest.TestCase):
    def test_inventory_and_unfinished_record(self):
        manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
        journeys = manifest['journeys']
        self.assertEqual(len(journeys), 64)
        self.assertEqual(len({j['name'] for j in journeys}), 64)
        self.assertEqual([j['id'] for j in journeys], [f'J{i:02}' for i in range(1, 65)])
        record = preparation_record()
        self.assertEqual(len(record['remaining']), 640)
        self.assertEqual(record['connected_passes'], 0)
        self.assertFalse(record['fixture_passes_are_integration'])
        self.assertTrue(all(r['status'] == 'deferred' for r in record['remaining']))

    def test_deterministic_outcomes(self):
        for state in ('success', 'denied', 'stale', 'pending', 'unavailable'):
            with self.subTest(state=state):
                self.assertEqual(fixture(state), fixture(state))
                self.assertEqual(set(fixture(state)), FIELDS)
        changed = fixture('success')
        changed['private_evidence'] = 'restricted'
        with self.assertRaises(ValueError):
            validate(changed)

    def test_pending_requires_owner_and_utc_follow_up(self):
        for key in ('pending_reason', 'next_actor', 'next_review_at'):
            row = fixture('pending')
            row[key] = None
            with self.assertRaises(ValueError):
                validate(row)
        with self.assertRaises(ValueError):
            instant('2026-11-17T10:00:00')

    def test_minor_units(self):
        for value in (True, -1, 0.1, float('inf'), float('nan'), '500000', 2**53):
            with self.subTest(value=value), self.assertRaises(ValueError):
                minor(value)
        self.assertEqual(minor(500000), 500000)

    def test_clock_before_equal_after_and_single_window(self):
        start = '2026-11-17T00:00:00Z'
        for method, hours in ((None, 48), ('card', 24), ('Whish Money', 48), ('OMT Pay', 48)):
            deadline = payment_deadline(start, method)
            self.assertEqual(deadline, instant(start) + timedelta(hours=hours))
            before = (deadline - timedelta(microseconds=1)).isoformat()
            self.assertEqual(payment_deadline(start, method, before), deadline + timedelta(hours=24))
            for attempt in (deadline, deadline + timedelta(microseconds=1)):
                self.assertEqual(payment_deadline(start, method, attempt.isoformat()), deadline)
        self.assertIsNone(payment_deadline(None, 'card'))
        self.assertLess(payment_deadline(start, 'card'), payment_deadline(start, None))

    def observations(self, route):
        return [Observation(step, {**fixture('success'), 'operation_id': f'sample-{i}'},
                            'provider_operation') for i, step in enumerate(ROUTES[route])]

    def test_route_checker_only_validates_observations(self):
        for route in ROUTES:
            with self.subTest(route=route):
                result = verify_route(route, self.observations(route))
                self.assertEqual(result['connected_acceptance'], 'deferred')

    def test_every_prerequisite_cannot_be_omitted_or_unresolved(self):
        for route, steps in ROUTES.items():
            for index in range(len(steps)):
                rows = self.observations(route)
                with self.subTest(route=route, index=index), self.assertRaises(ValueError):
                    verify_route(route, rows[:index] + rows[index + 1:])
                for state in ('pending', 'denied', 'stale', 'unavailable'):
                    changed = deepcopy(rows)
                    changed[index].receipt.update(fixture(state))
                    with self.assertRaises(ValueError):
                        verify_route(route, changed)

    def test_scope_revision_and_synthetic_source_denied(self):
        for key, value in (('subject_id', 'other'), ('watch_id', 'other'),
                           ('organization_id', 'other'), ('expected_revision', 2)):
            rows = self.observations('customization')
            rows[-1].receipt[key] = value
            with self.assertRaises(ValueError):
                verify_route('customization', rows)
        rows = self.observations('private_purchase')
        rows[0] = Observation(rows[0].step, rows[0].receipt, 'fixture')
        with self.assertRaises(ValueError):
            verify_route('private_purchase', rows)

    def test_business_has_no_fabricated_inspection(self):
        for route in ('dealer_purchase', 'brand_purchase'):
            self.assertNotIn('independent_pass', ROUTES[route])
        self.assertIn('independent_pass', ROUTES['private_purchase'])


if __name__ == '__main__':
    unittest.main()
