from unittest.mock import patch

import pytest

from driver import Missing, reconcile_snapshot
from native import Unavailable
from observations import read_orders

NOTICE_EVENT = '00000000-0000-4000-8000-000000000001'
PAYMENT_EVENT = '00000000-0000-4000-8000-000000000002'
INBOX = {'event_id': PAYMENT_EVENT, 'source': 'orders', 'consumer': 'communications-order-timeline'}


def payment():
    return dict(
        operation_id='test-callback', amount_minor=125, currency='USD', paid=True,
        order_state='paid_held', attempt_state='confirmed', payment_revision=3,
        attempt={'id': 'test-attempt', 'order_id': 'test-order'},
        retained_quote={'quote_id': 'test-quote', 'snapshot': dict(
            currency='USD', price_minor=100, buyer_fee_minor=15, seller_commission_minor=5,
            seller_net_minor=95, shipping_minor=10, tax_minor=0, payable_minor=125)},
        notice_event_id=NOTICE_EVENT, notice_id='test-notice',
        inbound={'event_id': 'test-callback', 'attempt_id': 'test-attempt'},
        intake=[{'id': 'test-intake', 'revision': 2, 'condition': 'حالة جيدة',
                 'operations': [{'id': 'test-intake-operation'}]}],
        postings=[{'id': 'test-posting', 'total_minor': 125, 'currency': 'USD',
                   'entries': [{'account': 'buyer_held', 'amount_minor': -125},
                               {'account': 'simulated_clearing', 'amount_minor': 125}]}],
        emitted=[{'event_id': PAYMENT_EVENT, 'destination': 'communications-order-timeline'}],
    )


def observe(row, *, inbox=True):
    records = [dict(event_id=PAYMENT_EVENT, record=INBOX)] if inbox else []
    with patch('observations.measure', side_effect=[[row], records]) as measure:
        answer = read_orders(['-d', 'test-orders'], ['-d', 'test-communications'])
    if row['emitted']:
        connection, query = measure.call_args.args
        assert connection == ['-d', 'test-communications']
        assert "inbox.source = 'orders'" in query
        assert "inbox.consumer = 'communications-order-timeline'" in query
        assert PAYMENT_EVENT in query
        assert NOTICE_EVENT not in query
    else:
        measure.assert_called_once()
    return answer


def test_projection_retains_product_records_under_callback_reference():
    row = payment()
    answer = observe(row)
    assert reconcile_snapshot(answer) == ['test-callback']
    assert answer['receipts'][0]['retained_quote'] == row['retained_quote']
    assert answer['receipts'][0]['attempt'] == row['attempt']
    assert answer['receipts'][0]['callback'] == row['inbound']
    assert answer['inbox'][0]['record'] == INBOX
    assert answer['journal'][0]['records'] == row['postings']
    assert answer['custody'][0]['records'] == row['intake']
    assert answer['custody'][0]['custody_reference'] == 'test-intake'
    assert answer['outbox'][0]['record'] == row['emitted'][0]


@pytest.mark.parametrize(('overrides', 'failure'), [
    ({'intake': []}, 'custody-coverage'),
    ({'emitted': []}, 'acknowledged-outbox-coverage'),
    ({'postings': []}, 'journal-coverage'),
    ({'paid': False}, 'current-held-payment'),
])
def test_missing_product_facts_fail_reconciliation(overrides, failure):
    with pytest.raises(Missing, match=failure):
        reconcile_snapshot(observe(payment() | overrides))


def test_custody_fact_without_durable_command_fails():
    row = payment()
    row['intake'][0]['operations'] = []
    with pytest.raises(Unavailable, match='durable-custody-operation'):
        observe(row)


def test_missing_retained_quote_fails_observation():
    with pytest.raises(Unavailable, match='retained-order-quote-economics'):
        observe(payment() | {'retained_quote': None})


def test_extra_journal_effects_and_unbalanced_entries_fail_reconciliation():
    row = payment()
    with pytest.raises(Missing, match='journal-reconciliation'):
        reconcile_snapshot(observe(row | {'postings': row['postings'] * 2}))
    row['postings'][0]['entries'][0]['amount_minor'] += 1
    with pytest.raises(Unavailable, match='balanced-held-journal'):
        observe(row)


def test_orders_projection_filters_demo_orders_and_inventory_before_reading_receipts():
    with patch('observations.measure', return_value=[]) as measure:
        answer = read_orders(['-d', 'test-orders'], ['-d', 'test-communications'])
    query = measure.call_args.args[1]
    assert 'to_jsonb(quote) AS retained_quote' in query
    assert 'quote.quote_id = attempt.quote_id AND quote.quote_revision = attempt.quote_revision' in query
    assert 'JOIN l08_watches inventory ON inventory.id = orders.watch_id' in query
    assert 'AND orders.is_demo IS FALSE AND inventory.is_demo IS FALSE' in query
    assert all(not records for records in answer.values())


def test_callback_receipt_cannot_replace_missing_consumer_inbox():
    answer = observe(payment(), inbox=False)
    assert answer['receipts'][0]['callback']['event_id'] == 'test-callback'
    with pytest.raises(Missing, match='acknowledged-inbox-coverage'):
        reconcile_snapshot(answer)


def test_each_emitted_event_requires_its_own_inbox_receipt():
    row = payment()
    row['emitted'].append({'event_id': '00000000-0000-4000-8000-000000000003'})
    with pytest.raises(Missing, match='acknowledged-inbox-coverage'):
        reconcile_snapshot(observe(row))


def test_matching_event_from_another_consumer_cannot_satisfy_reconciliation():
    from contextlib import closing
    import sqlite3

    with closing(sqlite3.connect(':memory:')) as database:
        database.execute('CREATE TABLE inbox(event_id TEXT, source TEXT, consumer TEXT)')
        database.execute('INSERT INTO inbox VALUES (?, ?, ?)',
                         (PAYMENT_EVENT, 'orders', 'test-other-consumer'))

        def measure(connection, query):
            if connection == ['-d', 'test-orders']:
                return [payment()]
            # Adapt the PostgreSQL projection while preserving the receipt predicates.
            query = query.replace('to_jsonb(inbox)', 'consumer').replace('::uuid', '')
            return [{'event_id': event, 'record': {'consumer': consumer}}
                    for event, consumer in database.execute(query)]

        with patch('observations.measure', side_effect=measure):
            connections = (['-d', 'test-orders'], ['-d', 'test-communications'])
            with pytest.raises(Missing, match='acknowledged-inbox-coverage'):
                reconcile_snapshot(read_orders(*connections))
            database.execute('INSERT INTO inbox VALUES (?, ?, ?)',
                             (PAYMENT_EVENT, 'orders', INBOX['consumer']))
            assert reconcile_snapshot(read_orders(*connections)) == ['test-callback']


def test_callback_acknowledgement_uses_only_the_bound_confirmed_receipt():
    from observations import confirmed_callback_exists

    ids = (PAYMENT_EVENT, '00000000-0000-4000-8000-000000000003',
           '00000000-0000-4000-8000-000000000004')
    connection = ['-d', 'test-orders']
    with patch('observations.measure', side_effect=[[], [{'event_id': PAYMENT_EVENT}]]) as measure:
        assert not confirmed_callback_exists(connection, *ids)
        assert confirmed_callback_exists(connection, *ids)
    actual_connection, query = measure.call_args.args
    assert actual_connection == connection
    for column, value in zip(('callback.event_id', 'attempt.id', 'attempt.order_id'), ids):
        assert f"{column} = '{value}'::uuid" in query
    assert "callback.outcome->>'code' = 'confirmed'" in query
    assert 'l13_order_quotes' not in query
    assert 'inbox' not in query
