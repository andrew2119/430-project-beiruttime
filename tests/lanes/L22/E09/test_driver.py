import contextlib
import io
import os
import unittest
from unittest.mock import patch

import driver


class DriverTests(unittest.TestCase):
    def test_print_mode_has_no_side_effects(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'E09_MODE': 'railway'}), \
                patch('sys.argv', ['driver.py', '--run-dir', '/tmp/test-e09-unused']), \
                patch.object(driver, 'Native', side_effect=AssertionError), \
                patch.object(driver.subprocess, 'run', side_effect=AssertionError), \
                patch.object(driver.Path, 'mkdir', side_effect=AssertionError), \
                contextlib.redirect_stdout(output):
            self.assertEqual(driver.main(), 0)
        self.assertEqual(output.getvalue().splitlines(), [
            *('railway up --service ' + s + ' --detach' for s in driver.SERVICES),
            'railway rollback --service orders'])

    def test_missing_adapter_names_every_required_case(self):
        class Unavailable:
            def call(self, action, request):
                raise driver.Missing(action + '-unavailable')
        result = driver.execute(Unavailable(), 'test-revision')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(len(result['results']), 15)
        self.assertTrue(all(r['state'] == 'failed' for r in result['results']))
        self.assertEqual(result['results'][0]['missing_capability'],
                         'authoritative-reads-unavailable')

    def test_substitute_cannot_count_as_connected(self):
        class Substitute:
            def call(self, action, request):
                return {**request, 'source': 'native', 'synthetic': True,
                        'seeded': False, 'state': 'passed'}
        result = driver.execute(Substitute(), 'test-revision')
        self.assertEqual(result['state'], 'failed')
        self.assertTrue(result['results'][0]['missing_capability'].endswith('connected-source'))

    def test_reconciliation_requires_authoritative_coverage_and_one_effect(self):
        receipt = {'operation_id': 'test-operation', 'amount_minor': 100,
                   'currency': 'USD', 'custody_reference': 'test-receipt', 'revision': 1}
        journal = {**receipt, 'effect_count': 1}
        self.assertEqual(driver.reconcile_reads([receipt], [journal], [receipt]),
                         ['test-operation'])
        for receipts, money, custody in (([], [], []), ([receipt], [], [receipt]),
                ([receipt], [{**journal, 'effect_count': 2}], [receipt]),
                ([receipt], [journal], [{**receipt, 'revision': 2}]),
                ([receipt, receipt], [journal, journal], [receipt, receipt])):
            with self.assertRaises(driver.Missing):
                driver.reconcile_reads(receipts, money, custody)


if __name__ == '__main__':
    unittest.main()
