"""Read authoritative payment and intake facts from the private Orders database."""

from uuid import UUID

from native import need
from restore import measure


PAYMENTS = """
SELECT callback.event_id AS operation_id, to_jsonb(callback) AS inbound,
       attempt.total_minor AS amount_minor, attempt.currency,
       orders.state AS order_state, attempt.state AS attempt_state,
       to_jsonb(attempt) AS attempt,
       to_jsonb(quote) AS retained_quote,
       orders.revision + orders.financial_revision AS payment_revision,
       (orders.state = 'paid_held' AND attempt.state = 'confirmed'
        AND orders.total_minor = attempt.total_minor AND orders.currency = attempt.currency
        AND orders.quote_id = attempt.quote_id AND orders.buyer_id = attempt.buyer_id
        AND NOT EXISTS (
            SELECT 1 FROM l13_money_operations movement
            WHERE movement.order_id = orders.id
              AND movement.kind IN ('refund', 'release') AND movement.state <> 'declined'
        ) AND NOT EXISTS (
            SELECT 1 FROM l13_money_reconciliations review WHERE review.order_id = orders.id
        )) AS paid,
       ARRAY(
           SELECT to_jsonb(fact) || jsonb_build_object('operations', ARRAY(
               SELECT to_jsonb(operation) FROM l08_operations operation
               WHERE operation.actor_key = 'user:' || fact.actor_id::text
                 AND operation.result @> jsonb_build_object(
                     'id', operation.id::text, 'resource_id', fact.id::text,
                     'revision', fact.revision, 'status', 'succeeded', 'final_handover', false)
               ORDER BY operation.id
           )) FROM l08_intake fact
           WHERE fact.order_id = orders.id ORDER BY fact.revision DESC, fact.id
       ) AS intake,
       ARRAY(
           SELECT to_jsonb(posting) || jsonb_build_object('entries', ARRAY(
               SELECT to_jsonb(entry) FROM l13_journal_entries entry
               WHERE entry.group_id = posting.id ORDER BY entry.account
           ))
           FROM l13_journal_groups posting
           WHERE posting.attempt_id = attempt.id AND posting.order_id = orders.id
           ORDER BY posting.id
       ) AS postings,
       ARRAY(
           SELECT jsonb_build_object('id', message.id, 'event_id', message.event_id,
                      'destination', message.destination, 'envelope', message.envelope,
                      'created_at', message.created_at)
           FROM outbox message JOIN l13_journal_groups posting
             ON message.envelope->'data'->>'journal_group_id' = posting.id::text
           WHERE posting.order_id = orders.id AND posting.attempt_id = attempt.id
             AND message.envelope->>'type' = 'orders.payment-confirmed.v1'
             AND message.destination = 'communications-order-timeline'
             AND message.envelope->>'source' = 'orders'
             AND message.envelope->>'subject' = orders.id::text
             AND message.envelope->'data'->>'order_id' = orders.id::text
           ORDER BY message.id
       ) AS emitted
FROM l13_payment_callbacks callback
JOIN l13_payment_attempts attempt ON attempt.id = callback.attempt_id
JOIN l08_orders orders ON orders.id = attempt.order_id
LEFT JOIN l13_order_quotes quote ON quote.order_id = orders.id
    AND quote.quote_id = attempt.quote_id AND quote.quote_revision = attempt.quote_revision
JOIN l08_watches inventory ON inventory.id = orders.watch_id
WHERE callback.outcome->>'code' = 'confirmed'
  AND orders.is_demo IS FALSE AND inventory.is_demo IS FALSE
ORDER BY callback.event_id
LIMIT 129
"""


def acknowledged_payments(connection):
    rows = measure(connection, """
        SELECT callback.event_id AS operation_id
        FROM l13_payment_callbacks callback
        JOIN l13_payment_attempts attempt ON attempt.id = callback.attempt_id
        JOIN l08_orders orders ON orders.id = attempt.order_id
        JOIN l08_watches inventory ON inventory.id = orders.watch_id
        WHERE callback.outcome->>'code' = 'confirmed'
          AND orders.is_demo IS FALSE AND inventory.is_demo IS FALSE
        ORDER BY callback.event_id
    """)
    return {str(UUID(row['operation_id'])) for row in rows}


def confirmed_callback_exists(connection, reference, attempt, order):
    event_id, attempt_id, order_id = (UUID(value) for value in (reference, attempt, order))
    rows = measure(connection, f"""
        SELECT callback.event_id
        FROM l13_payment_callbacks callback
        JOIN l13_payment_attempts attempt ON attempt.id = callback.attempt_id
        WHERE callback.event_id = '{event_id}'::uuid
          AND attempt.id = '{attempt_id}'::uuid
          AND attempt.order_id = '{order_id}'::uuid
          AND callback.outcome->>'code' = 'confirmed'
    """)
    return bool(rows)


def payment_inbox(connection, rows):
    events = sorted({str(UUID(message['event_id'])) for row in rows for message in row['emitted']})
    if not events:
        return {}
    event_list = ', '.join(f"'{event}'::uuid" for event in events)
    records = measure(connection, f"""
        SELECT inbox.event_id, to_jsonb(inbox) AS record
        FROM inbox
        WHERE inbox.source = 'orders'
          AND inbox.consumer = 'communications-order-timeline'
          AND inbox.event_id IN ({event_list})
        ORDER BY inbox.event_id
    """)
    by_event = {event: [] for event in events}
    for row in records:
        by_event[row['event_id']].append(row['record'])
    return by_event


def read_orders(connection, communications):
    rows = measure(connection, PAYMENTS)
    need(len(rows) <= 128, 'bounded-payment-observations')
    inbox = payment_inbox(communications, rows)
    answer = {name: [] for name in ('receipts', 'journal', 'custody', 'inbox', 'outbox')}
    for row in rows:
        reference = {'operation_id': row['operation_id']}
        quote = row['retained_quote']
        snapshot = quote['snapshot'] if quote else {}
        components = ('price_minor', 'buyer_fee_minor', 'seller_commission_minor',
                      'seller_net_minor', 'shipping_minor', 'tax_minor', 'payable_minor')
        need(all(type(snapshot.get(key)) is int for key in components)
             and snapshot.get('currency') == row['currency']
             and snapshot['payable_minor'] == row['amount_minor'],
             'retained-order-quote-economics')
        intake, postings = row['intake'], row['postings']
        custody = dict(custody_reference=intake[0]['id'] if intake else None,
                       revision=intake[0]['revision'] if intake else None)
        answer['receipts'].append(dict(
            reference, **custody, **{key: row[key] for key in (
                'amount_minor', 'currency', 'order_state', 'attempt_state',
                'payment_revision', 'paid', 'attempt', 'retained_quote')}, callback=row['inbound']))
        events = sorted({message['event_id'] for message in row['emitted']})
        if all(inbox[event] for event in events):
            for event in events:
                answer['inbox'].extend(dict(reference, record=record) for record in inbox[event])
        if intake:
            need(all(len(fact['operations']) == 1 for fact in intake),
                 'durable-custody-operation')
            answer['custody'].append(dict(reference, **custody, records=intake))
        if postings:
            posting = postings[0]
            balances = {entry['account']: entry['amount_minor'] for entry in posting['entries']}
            need(balances == {'simulated_clearing': posting['total_minor'],
                              'buyer_held': -posting['total_minor']}, 'balanced-held-journal')
            answer['journal'].append(dict(reference, effect_count=len(postings), records=postings,
                                          amount_minor=posting['total_minor'], currency=posting['currency']))
        answer['outbox'].extend(dict(reference, record=message) for message in row['emitted'])
    return answer
