import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('minimum_offers', ROOT / 'services/pricing/modules/minimum-offers/service.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Provider:
    def __init__(self, facts):
        self.facts = facts
        self.timeout = False

    @contextmanager
    def locked(self, command, actor, timeout_seconds):
        assert timeout_seconds == 2
        if self.timeout:
            raise TimeoutError()
        yield self.facts


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name) / 'rules.db')
        self.command = json.loads((ROOT / 'packages/contracts-pricing/minimum-offers/fixtures.json').read_text())['command']
        self.facts = module.Facts('seller', 'business', 'listing', 'watch', 2, 3, 'quote', 4, True, True, 'fixed_price', False)
        self.provider = Provider(self.facts)
        self.service = module.MinimumOffers(self.path, self.provider)

    def save(self, **updates):
        return self.service.save(dict(self.command, **updates), 'seller')

    def test_private_response_envelopes(self):
        fixtures = json.loads((ROOT / 'packages/contracts-pricing/minimum-offers/fixtures.json').read_text())
        self.assertEqual(self.save(source_revision=99), fixtures['stale'])
        self.provider.timeout = True
        self.assertEqual(self.save(), fixtures['lost_response'])
        self.assertEqual(self.service.read(self.command, 'seller'), fixtures['unavailable'])
        self.provider.timeout = False
        self.assertEqual(self.save(), fixtures['success'])
        current = dict(self.command, operation_id='current')
        self.assertEqual(self.service.read(current, 'seller'), fixtures['current'])
        self.assertEqual(self.service.read(self.command, 'seller', operation=True), fixtures['success'])
        self.assertEqual(self.save(operation_id='second', expected_revision=1, minimum_minor=12000)['revision'], 2)
        self.service = module.MinimumOffers(self.path, self.provider)
        self.assertEqual(self.service.read(self.command, 'seller', operation=True), fixtures['success'])
        for result in (self.service.save(self.command, 'buyer'),
                       self.service.read(self.command, 'buyer'),
                       self.service.read(self.command, 'buyer', operation=True)):
            self.assertEqual(result, fixtures['denied'])

    def test_positive_and_boundary(self):
        self.assertEqual(self.save()['state'], 'saved')
        with self.service.transaction() as db:
            for cents, state in [(9999, 'declined'), (10000, 'review_required'), (10001, 'review_required')]:
                self.assertEqual(self.service.evaluate(db, self.facts, 'buyer', cents), {'state': state})

    def test_duplicate_restart_and_outbox_privacy(self):
        first = self.save()
        self.service = module.MinimumOffers(self.path, self.provider)
        self.assertEqual(first, self.save())
        self.assertEqual(first, self.service.read(self.command, 'seller', operation=True))
        self.assertEqual(self.save(minimum_minor=11000)['state'], 'denied')
        with sqlite3.connect(self.path) as db:
            events = db.execute('SELECT event FROM l18_minimum_outbox').fetchall()
            self.assertEqual(len(events), 1)
            self.assertNotIn('minimum', json.loads(events[0][0]))
            self.assertNotIn('10000', events[0][0])

    def test_timeout_then_same_reference(self):
        self.provider.timeout = True
        self.assertEqual(self.save()['state'], 'pending')
        self.provider.timeout = False
        self.assertEqual(self.save()['revision'], 1)
        self.assertEqual(self.save()['revision'], 1)

    def test_scope_and_revocation(self):
        self.save()
        for changes in [dict(active=False), dict(permitted=False), dict(organization_id='elsewhere'), dict(watch_id='another')]:
            self.provider.facts = replace(self.facts, **changes)
            for result in [self.save(), self.service.read(self.command, 'seller'), self.service.read(self.command, 'seller', operation=True)]:
                self.assertEqual(result['state'], 'denied')
                self.assertNotIn('minimum_minor', result)
        self.provider.facts = self.facts
        self.assertEqual(self.service.save(self.command, 'buyer')['state'], 'denied')
        self.assertEqual(self.service.read(self.command, 'buyer')['state'], 'denied')

    def test_stale_sources_and_revision(self):
        for key in ['source_revision', 'policy_revision', 'quote_revision', 'expected_revision']:
            self.assertEqual(self.save(**{key: 99})['state'], 'stale')
        self.assertEqual(self.save(quote_id='other')['state'], 'stale')
        self.save()
        self.assertEqual(self.save(operation_id='second')['state'], 'stale')

    def test_committed_agreement_and_modes(self):
        self.save()
        for changes in [dict(committed=True), dict(mode='auction'), dict(mode='offers_only')]:
            self.provider.facts = replace(self.facts, **changes)
            self.assertEqual(self.save(operation_id='second', expected_revision=1)['state'], 'denied')
        self.provider.facts = self.facts
        self.assertEqual(self.service.read(self.command, 'seller')['minimum_minor'], 10000)

    def test_remove_threshold_and_independent_blocks(self):
        self.save()
        self.assertEqual(self.save(operation_id='remove', expected_revision=1, minimum_minor=None)['state'], 'saved')
        with self.service.transaction() as db:
            self.assertEqual(self.service.evaluate(db, self.facts, 'buyer', 1)['state'], 'review_required')
            self.service.set_own_block(db, 'seller', 'buyer', True)
            self.service.set_own_block(db, 'buyer', 'seller', True)
            self.service.set_own_block(db, 'seller', 'buyer', False)
            self.assertEqual(self.service.evaluate(db, self.facts, 'buyer', 20000), {'state': 'declined'})
            self.service.set_own_block(db, 'buyer', 'seller', False)
            self.assertEqual(self.service.evaluate(db, self.facts, 'buyer', 20000), {'state': 'review_required'})

    def test_invalid_money_and_bounds(self):
        for amount in [True, False, 0, -1, 1.5, '100', float('inf'), module.LIMIT + 1]:
            self.assertEqual(self.save(minimum_minor=amount)['state'], 'denied')
        self.assertEqual(self.save(subject_id='x' * 97)['state'], 'denied')
        self.assertEqual(self.save(schema_version=True)['state'], 'denied')
        self.assertEqual(self.save()['state'], 'saved')

    def test_operation_cannot_cross_subject(self):
        self.save()
        self.provider.facts = replace(self.facts, subject_id='other')
        result = self.service.read(dict(self.command, subject_id='other'), 'seller', operation=True)
        self.assertEqual(result['state'], 'denied')


if __name__ == '__main__':
    unittest.main()

class AdapterTest(unittest.TestCase):
    def test_bounds_and_duplicate_keys(self):
        adapter_spec = importlib.util.spec_from_file_location('minimum_adapter', ROOT / 'services/pricing/modules/minimum-offers/adapter.py')
        adapter = importlib.util.module_from_spec(adapter_spec)
        adapter_spec.loader.exec_module(adapter)
        for raw in [b'{' , b'{"actor_id":"one","actor_id":"two"}', b'\xff']:
            self.assertEqual(adapter.command_response(None, raw, 'seller')[0], 400)
        self.assertEqual(adapter.command_response(None, b'x' * 4097, 'seller')[0], 403)
        self.assertEqual(adapter.command_response(None, b'{}', None)[0], 403)
        self.assertEqual(adapter.private_headers()['Cache-Control'], 'no-store')
