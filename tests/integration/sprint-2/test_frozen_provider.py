"""Pure freeze-double checks. Commercial outcomes remain unproven."""
from copy import deepcopy
import unittest
import json
from pathlib import Path

from frozen_provider import (Denied, FrozenSources, LostResponse, Stale,
                             authorize_job, proxy_v2)
from proof import payment_deadline

NOW = '2026-11-17T00:00:00Z'


def auction():
    return dict(opening_minor=400000, current_minor=400000, leader_id=None,
                sequence=0, increment_bands=[dict(from_minor=0, step_minor=10000)], maxima=[])


def bid(state, bidder, amount, sequence, kind='maximum'):
    result = proxy_v2(state, dict(kind=kind, bidder_id=bidder, amount_minor=amount, sequence=sequence))
    return {**state, **result, 'sequence': sequence}


def job():
    quote = dict(buyer_id='sample-buyer', order_id='sample-order', watch_id='sample-watch',
                 quote_id='sample-quote', quote_revision=2, currency='USD', total_minor=500000)
    return dict(current_identity=True, current_membership=True, current_assignment=True,
                current_revision=True, current_consent=True, current_approval=True,
                current_custody=True, allocated=True, accepted_scope=True,
                selected_business='sample-brand', job_business='sample-brand',
                kind='customization', business_type='brand', assessor_id='sample-assessor',
                approver_id='sample-approver', quality_reviewer_id='sample-quality',
                eligibility_reviewer_id='sample-reviewer', buyer_id='sample-buyer',
                readiness={**quote, 'state': 'paid_held', 'payment_operation_id': 'sample-payment',
                           'payment_revision': 1, 'order_kind': 'customization'}, quote=quote)


class FrozenProviderTests(unittest.TestCase):
    def test_proxy_examples_full_step_and_inactive_ceiling(self):
        first = bid(auction(), 'sample-maya', 450000, 1)
        self.assertEqual(first['current_minor'], 400000)
        second = bid(first, 'sample-rami', 420000, 2, 'manual')
        self.assertEqual(second['current_minor'], 430000)
        self.assertEqual([b['amount_minor'] for b in second['bids']], [420000, 430000])
        for amount in (445000, 450000):
            result = bid(second, 'sample-rami', amount, 3, 'manual')
            self.assertEqual(result['leader_id'], 'sample-rami')
            self.assertFalse(result['maxima'][0]['active'])
            self.assertEqual(len(result['bids']), 1)
        for row in second['bids']:
            self.assertEqual(set(row), {'bidder_id', 'amount_minor', 'automatic'})

    def test_proxy_raise_stale_equal_and_band_selection(self):
        first = bid(auction(), 'sample-a', 450000, 1)
        raised = bid(first, 'sample-a', 460000, 2)
        self.assertEqual(raised['bids'], [])
        with self.assertRaises(Denied):
            bid(raised, 'sample-a', 450000, 3)
        with self.assertRaises(Stale):
            bid(raised, 'sample-b', 460000, 2)
        equal = bid(first, 'sample-b', 450000, 2)
        self.assertEqual(equal['leader_id'], 'sample-b')
        self.assertFalse(equal['maxima'][0]['active'])
        with self.assertRaises(Denied):
            bid(first, 'sample-b', 400000, 2)
        manual = bid(auction(), 'sample-a', 440000, 1, 'manual')
        with self.assertRaises(Denied):
            bid(manual, 'sample-a', 400000, 2)
        first['increment_bands'].append(dict(from_minor=420000, step_minor=20000))
        result = bid(first, 'sample-b', 420000, 2, 'manual')
        self.assertEqual(result['current_minor'], 440000)

    def test_pricing_exact_economics_preview_boundary_and_scope(self):
        provider = FrozenSources()
        for kind, total in (('watch', 515000), ('job', 500000)):
            quote = provider.quote(kind, 'sample-buyer', kind, NOW)
            self.assertEqual(quote['total_minor'], total)
            self.assertEqual(quote['business_fee_minor'], 25000)
        for consumer, buyer, current in (('public', 'sample-buyer', True),
                                         ('orders', 'other', True), ('orders', 'sample-buyer', False)):
            with self.assertRaises(Denied):
                provider.validate_quote('watch', consumer, buyer, NOW, current)
        provider.validate_quote('watch', 'orders', 'sample-buyer', '2026-11-17T00:14:59.999999Z', True)
        for at in ('2026-11-17T00:15:00Z', '2026-11-17T00:15:00.000001Z'):
            with self.assertRaises(Stale):
                provider.validate_quote('watch', 'orders', 'sample-buyer', at, True)

    def test_commit_lost_response_restart_duplicate_conflict_and_stale(self):
        provider = FrozenSources()
        provider.quote('sample-quote', 'sample-buyer', 'watch', NOW)
        body = dict(buyer_id='sample-buyer', order_id='sample-order', quote_revision=1,
                    total_minor=515000, committed_at=NOW)
        with self.assertRaises(Stale):
            provider.commit_quote('sample-quote', 'orders', 'stale', {**body, 'quote_revision': 2})
        with self.assertRaises(Denied):
            provider.commit_quote('sample-quote', 'other', 'wrong-consumer', body)
        with self.assertRaises(LostResponse):
            provider.commit_quote('sample-quote', 'orders', 'sample-commit', body, lose_response=True)
        restarted = FrozenSources(provider.store)
        result = restarted.commit_quote('sample-quote', 'orders', 'sample-commit', body)
        self.assertIsNone(result['expires_at'])
        self.assertEqual(result, restarted.retained('sample-quote', 'orders'))
        self.assertEqual(len(restarted.store['receipts']), 1)
        with self.assertRaises(Denied):
            restarted.commit_quote('sample-quote', 'orders', 'sample-commit', {**body, 'total_minor': 1})
        restarted.quote('sample-other-quote', 'sample-buyer', 'watch', NOW)
        with self.assertRaises(Denied):
            restarted.commit_quote('sample-other-quote', 'orders', 'sample-commit', body)
        # Retained economics survive time, but current validation is independent.
        with self.assertRaises(Denied):
            restarted.validate_quote('sample-quote', 'orders', 'sample-buyer', '2027-01-01T00:00:00Z', False)

    def test_notice_actual_bindings_lost_duplicate_and_conflict(self):
        provider = FrozenSources()
        intent = dict(event_id='sample-event', order_id='sample-order', buyer_id='sample-buyer')
        receipt = dict(**intent, notice_id='sample-notice', notified_at=NOW, verified_delivery_recorded=True)
        durable = dict(**intent, notice_id='sample-notice', available_at=NOW, verified_delivery_recorded=True)
        self.assertEqual(provider.store['notices'], {})
        for key in receipt:
            changed = {**receipt, key: False if key == 'verified_delivery_recorded' else 'other'}
            with self.subTest(key=key), self.assertRaises((Denied, ValueError)):
                provider.payment_notice('communications', intent, changed, durable, 'wrong-'+key)
        with self.assertRaises(Denied):
            provider.payment_notice('orders', intent, receipt, durable, 'wrong-producer')
        with self.assertRaises(LostResponse):
            provider.payment_notice('communications', intent, receipt, durable, 'sample-notice-op', True)
        restarted = FrozenSources(provider.store)
        first = restarted.payment_notice('communications', intent, receipt, durable, 'sample-notice-op')
        self.assertEqual(first['notified_at'], NOW)
        self.assertEqual(len(restarted.store['notices']), 1)
        with self.assertRaises(Denied):
            restarted.payment_notice('communications', intent, {**receipt, 'notice_id': 'different'}, durable, 'sample-notice-op')

    def test_published_freeze_fixture_and_schema(self):
        root = Path(__file__).parent
        values = json.loads((root / 'freeze-fixtures.json').read_text())
        proxy = values['proxy']
        self.assertEqual(proxy_v2(proxy['input'], proxy['command']), proxy['expected'])
        schema = json.loads((root / 'schema.json').read_text())
        for name, value in [('proxy_command', proxy['command']),
                            ('quote_commit', values['quote_commit']),
                            ('payment_notice', values['notice'])]:
            shape = schema['$defs'][name]
            self.assertEqual(set(shape['required']), set(value))
            self.assertFalse(shape['additionalProperties'])
        self.assertFalse(values['integration_proof'])

    def test_pre_notice_attempt_denied(self):
        with self.assertRaises(ValueError):
            payment_deadline(NOW, 'card', '2026-11-16T23:59:59Z')

    def test_staffing_independence_for_every_job_route(self):
        for kind, business in (('customization', 'brand'), ('service', 'brand'),
                               ('service', 'dealer')):
            facts = job()
            facts.update(kind=kind, business_type=business)
            facts['readiness']['order_kind'] = kind
            self.assertEqual(authorize_job(facts), 'authorized_expectation')
            for first, second in (('assessor_id', 'approver_id'),
                                  ('assessor_id', 'quality_reviewer_id'),
                                  ('approver_id', 'quality_reviewer_id')):
                with self.subTest(kind=kind, business=business, roles=(first, second)):
                    with self.assertRaises(Denied):
                        authorize_job({**facts, second: facts[first]})

    def test_quote_and_payment_must_bind_current_case_buyer(self):
        for kind, business in (('customization', 'brand'), ('service', 'brand'),
                               ('service', 'dealer')):
            facts = job()
            facts.update(kind=kind, business_type=business)
            facts['readiness']['order_kind'] = kind
            with self.subTest(kind=kind, business=business), self.assertRaises(Denied):
                authorize_job({**facts, 'buyer_id': 'sample-other-buyer'})

    def test_current_job_prerequisites_and_readiness_every_binding(self):
        facts = job()
        self.assertEqual(authorize_job(facts), 'authorized_expectation')
        for key in [k for k in facts if k.startswith('current_')] + ['allocated', 'accepted_scope']:
            with self.subTest(key=key), self.assertRaises(Denied):
                authorize_job({**facts, key: False})
        for key in facts['quote']:
            changed = deepcopy(facts)
            changed['readiness'][key] = 3 if key in {'quote_revision', 'total_minor'} else 'other'
            with self.subTest(key=key), self.assertRaises(Denied):
                authorize_job(changed)
        for change in ({'selected_business': 'other'}, {'business_type': 'dealer'},
                       {'quality_reviewer_id': 'sample-assessor'},
                       {'eligibility_reviewer_id': 'sample-buyer'},
                       {'eligibility_reviewer_id': 'sample-approver'}):
            with self.assertRaises(Denied):
                authorize_job({**facts, **change})
        facts['kind'] = 'service'
        facts['business_type'] = 'dealer'
        with self.assertRaises(Denied):
            authorize_job(facts)
        facts['readiness']['order_kind'] = 'service'
        for change in ({'kind': 'other'}, {'business_type': 'other'}):
            with self.assertRaises(Denied):
                authorize_job({**facts, **change})
        self.assertEqual(authorize_job(facts), 'authorized_expectation')
        for state in ('pending', 'unpaid'):
            facts['readiness']['state'] = state
            with self.assertRaises(Denied):
                authorize_job(facts)


if __name__ == '__main__':
    unittest.main()
