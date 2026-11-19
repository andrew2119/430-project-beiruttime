"""Read-only financial projection over authenticated immutable Orders facts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import io
import json
import re
import sqlite3
from typing import Callable

MAX_MINOR = 9007199254740991
KINDS = ('gross', 'buyer_fee_collected', 'fee_collected', 'fee_owed', 'refund', 'payout')
REFERENCE = re.compile(r'^[A-Za-z0-9_-]{1,100}$')


def reference(value):
    if not isinstance(value, str) or not REFERENCE.fullmatch(value):
        raise ValueError('invalid_reference')
    return value


def integer(value, minimum=0, maximum=MAX_MINOR):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_integer')
    return value


def instant(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('invalid_instant')
    result = datetime.fromisoformat(value[:-1] + '+00:00')
    if result.utcoffset().total_seconds() != 0:
        raise ValueError('invalid_instant')
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class Authority:
    actor_id: str
    organization_id: str | None
    subject_id: str
    revision: int
    allowed: bool
    operator: bool = False
    # Current readable order IDs, supplied by the authority provider.
    order_ids: frozenset[str] = frozenset()


class Projection:
    def __init__(self, database: str):
        self.db = sqlite3.connect(database, timeout=2)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS l22_report_health (
            id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS l22_report_watermark (
            id INTEGER PRIMARY KEY CHECK(id=1), highest INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS l22_report_events (
            sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS l22_report_operations (
            operation_id TEXT PRIMARY KEY, binding TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    @property
    def checkpoint(self):
        return self.db.execute('SELECT COALESCE(MAX(sequence),0) FROM l22_report_events').fetchone()[0]

    def ingest(self, feed, now):
        if self.db.execute('SELECT state FROM l22_report_health WHERE id=1').fetchone():
            raise ValueError('reconciliation_required')
        try:
            return self._ingest(feed, now)
        except (ValueError, KeyError, TypeError, OverflowError):
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO l22_report_health VALUES (1,'drift')")
            raise

    def _ingest(self, feed, now):
        if feed.get('schema_version') != 'orders.financial-feed.v1':
            raise ValueError('invalid_feed')
        high = integer(feed['high_watermark'])
        with self.db:
            prior = self.db.execute('SELECT highest FROM l22_report_watermark WHERE id=1').fetchone()
            highest = max(high, prior[0] if prior else 0, self.checkpoint)
            self.db.execute('INSERT OR REPLACE INTO l22_report_watermark VALUES (1,?)', (highest,))
        if high < highest:
            return 'pending'
        checked = instant(feed['checked_at'])
        if checked > now or (now - checked).total_seconds() > 60:
            return 'pending'
        events = feed['events']
        if not isinstance(events, list) or len(events) > 500 or len(canonical(feed).encode('utf-8')) > 1048576:
            raise ValueError('invalid_feed')
        with self.db:
            for event in events:
                self._event(event, checked)
                payload = canonical(event)
                same = self.db.execute('SELECT sequence,payload FROM l22_report_events WHERE event_id=?', (event['event_id'],)).fetchone()
                if same:
                    if same != (event['sequence'], payload):
                        raise ValueError('conflicting_duplicate')
                    continue
                if event['sequence'] != self.checkpoint + 1 or event['sequence'] > high:
                    raise ValueError('sequence_gap')
                self.db.execute('INSERT INTO l22_report_events VALUES (?,?,?)', (event['sequence'], event['event_id'], payload))
            if high < self.checkpoint:
                raise ValueError('backwards_checkpoint')
            # Validate all cumulative snapshots before acknowledging the batch.
            self._facts()
        return 'ready' if high == self.checkpoint else 'pending'

    def _event(self, event, checked):
        required = {'sequence','event_id','order_id','watch_id','seller_id','organization_id','source_revision','quote_id','quote_revision','policy_revision','kind','state','amount_minor','currency','occurred_at','postings'}
        if set(event) != required:
            raise ValueError('invalid_fact')
        integer(event['sequence'], 1)
        for key in ('event_id','order_id','watch_id','seller_id','quote_id','policy_revision'):
            reference(event[key])
        if event['organization_id'] is not None:
            reference(event['organization_id'])
        integer(event['source_revision'], 1)
        integer(event['quote_revision'], 1)
        amount = integer(event['amount_minor'])
        if event['currency'] != 'USD' or event['kind'] not in KINDS or event['state'] not in ('confirmed', 'pending') or instant(event['occurred_at']) > checked:
            raise ValueError('invalid_fact')
        postings = event['postings']
        if not isinstance(postings, list) or len(postings) != 2:
            raise ValueError('unbalanced')
        for posting in postings:
            if set(posting) != {'account','minor'}:
                raise ValueError('invalid_posting')
            reference(posting['account'])
            integer(posting['minor'], -MAX_MINOR)
        if postings[0]['account'] == postings[1]['account'] or sorted(p['minor'] for p in postings) != [-amount, amount]:
            raise ValueError('unbalanced')

    def _facts(self):
        rows = {}
        for (payload,) in self.db.execute('SELECT payload FROM l22_report_events ORDER BY sequence'):
            event = json.loads(payload)
            order = rows.setdefault(event['order_id'], {'order_id':event['order_id'], 'watch_id':event['watch_id'], 'seller_id':event['seller_id'], 'organization_id':event['organization_id'], 'quote_id':event['quote_id'], 'quote_revision':event['quote_revision'], 'policy_revision':event['policy_revision'], 'revision':0, 'facts':{}, 'pending':{}, 'occurred_at':event['occurred_at']})
            if any(order[key] != event[key] for key in ('watch_id','seller_id','organization_id','quote_id','quote_revision','policy_revision')):
                raise ValueError('changed_binding')
            kind = event['kind']
            old = order['pending'].get(kind) or order['facts'].get(kind)
            if old and event['source_revision'] <= old['source_revision']:
                raise ValueError('backwards_revision')
            confirmed = order['facts'].get(kind)
            if confirmed and kind != 'fee_owed' and event['amount_minor'] < confirmed['amount_minor']:
                raise ValueError('backwards_amount')
            order['pending'].pop(kind, None)
            order['facts' if event['state'] == 'confirmed' else 'pending'][kind] = event
            order['revision'] = max(order['revision'], event['source_revision'])
            order['occurred_at'] = event['occurred_at']
        for order in rows.values():
            amounts = {kind:order['facts'].get(kind, {}).get('amount_minor', 0) for kind in KINDS}
            if amounts['refund'] > amounts['gross'] or amounts['payout'] > max(0, amounts['gross'] - amounts['refund'] - amounts['fee_collected']):
                raise ValueError('inconsistent_totals')
            order.update(amounts)
            order['net'] = amounts['gross'] - amounts['refund'] - amounts['fee_collected']
        return rows

    def read(self, request, principal, authorize: Callable, feed_reader: Callable, now=None):
        now = now or datetime.now(timezone.utc)
        operation = request.get('operation_id', '')
        result = {'schema_version':'financial-reports.v1', 'operation_id':operation, 'subject_id':None, 'watch_id':None, 'actor_id':None, 'organization_id':None, 'expected_revision':None, 'state':'unavailable', 'revision':None, 'pending_reason':None, 'next_actor':'operator', 'next_review_at':None}
        def stop(state, reason):
            return {**result, 'state':state, 'pending_reason':reason}
        try:
            if set(request) != {'operation_id','actor_id','organization_id','subject_id','expected_revision','page','page_size','order_id','view','action'}:
                return stop('denied', 'invalid_request')
            for key in ('operation_id','actor_id','subject_id'):
                reference(request[key])
            if request['organization_id'] is not None:
                reference(request['organization_id'])
            if request['order_id'] is not None:
                reference(request['order_id'])
            integer(request['expected_revision'], 1)
            integer(request['page'], 1, 10000)
            integer(request['page_size'], 1, 50)
            if request['action'] not in ('read','export','receipt') or (request['action'] == 'receipt' and not request['order_id']) or (request['action'] == 'export' and request['page'] != 1):
                return stop('denied', 'invalid_request')
            if request['view'] not in ('seller','operator'):
                return stop('denied', 'invalid_request')
            authority = authorize(principal, request['organization_id'], request['subject_id'], timeout=2)
            if not isinstance(authority, Authority) or not authority.allowed or authority.actor_id != principal or request['actor_id'] != principal or authority.subject_id != request['subject_id'] or authority.organization_id != request['organization_id'] or (request['view'] == 'operator' and not authority.operator):
                return stop('denied', 'scope_denied')
            result.update(actor_id=authority.actor_id,organization_id=authority.organization_id,subject_id=authority.subject_id,expected_revision=request['expected_revision'],revision=authority.revision)
            if authority.revision != request['expected_revision']:
                return stop('stale', 'stale_revision')
            binding = canonical(request)
            with self.db:
                prior = self.db.execute('SELECT binding FROM l22_report_operations WHERE operation_id=?', (operation,)).fetchone()
                if prior and prior[0] != binding:
                    return stop('denied', 'operation_conflict')
                self.db.execute('INSERT OR IGNORE INTO l22_report_operations VALUES (?,?)', (operation,binding))
            # A durable binding precedes the bounded call, so a lost response retries it.
            feed = feed_reader(self.checkpoint, limit=500, timeout=2)
            state = self.ingest(feed, now)
            if state != 'ready':
                return stop(state, 'feed_delayed')
            rows = self._facts()
            scoped = [row for row in rows.values() if row['order_id'] in authority.order_ids and (authority.operator and request['view'] == 'operator' or row['seller_id'] == authority.subject_id and row['organization_id'] == authority.organization_id)]
            if request['order_id']:
                scoped = [row for row in scoped if row['order_id'] == request['order_id']]
                if not scoped:
                    return stop('denied', 'scope_denied')
            # Recheck after provider work: revocation or reassignment fences late answers.
            current = authorize(principal, request['organization_id'], request['subject_id'], timeout=2)
            if current != authority:
                return stop('denied', 'scope_changed')
            if any(row['pending'] for row in scoped):
                return stop('pending', 'source_pending')
            scoped.sort(key=lambda row:row['order_id'])
            totals = {key:integer(sum(row[key] for row in scoped), -MAX_MINOR if key == 'net' else 0) for key in (*KINDS,'net')}
            public = [{key:row[key] for key in ('order_id','watch_id','quote_id','quote_revision','policy_revision','revision','occurred_at',*KINDS,'net')} for row in scoped]
            if request['action'] == 'export' and len(public) > 1000:
                return stop('unavailable', 'export_limit')
            start = (request['page'] - 1) * request['page_size']
            selected = public if request['action'] == 'export' else public[start:start+request['page_size']]
            answer = {**result, 'state':'ready', 'next_actor':None, 'currency':'USD', 'simulated':True, 'checkpoint':self.checkpoint, 'checked_at':feed['checked_at'], 'total_count':len(public), 'totals':totals, 'items':selected, 'page':request['page'], 'page_size':request['page_size']}
            if request['action'] == 'receipt':
                answer['watch_id'] = scoped[0]['watch_id']
            if request['view'] == 'operator':
                trial = {}
                for row in scoped:
                    for event in row['facts'].values():
                        for posting in event['postings']:
                            trial[posting['account']] = integer(trial.get(posting['account'], 0) + posting['minor'], -MAX_MINOR)
                answer.update(trial_balance=trial, take_rate={'numerator':integer(totals['fee_collected'] + totals['buyer_fee_collected']), 'denominator':totals['gross']} if totals['gross'] else None)
            return answer
        except (TimeoutError, ConnectionError, OSError):
            return stop('unavailable', 'provider_unavailable')
        except (ValueError, KeyError, TypeError, OverflowError):
            return stop('drift', 'invalid_source')

    def operation(self, operation_id, principal, authorize, feed_reader, now=None):
        reference(operation_id)
        prior = self.db.execute('SELECT binding FROM l22_report_operations WHERE operation_id=?', (operation_id,)).fetchone()
        if not prior:
            return {'schema_version':'financial-reports.v1','operation_id':operation_id,'subject_id':None,'watch_id':None,'actor_id':None,'organization_id':None,'expected_revision':None,'state':'denied','revision':None,'pending_reason':'scope_denied','next_actor':'operator','next_review_at':None}
        return self.read(json.loads(prior[0]), principal, authorize, feed_reader, now)


def export_csv(answer, locale):
    if locale not in ('en','ar') or answer.get('state') != 'ready' or answer['total_count'] > 1000 or len(answer['items']) != answer['total_count']:
        raise ValueError('export_unavailable')
    columns = ('order_id','gross','buyer_fee_collected','fee_collected','fee_owed','refund','net','payout')
    headers = ('Order','Gross USD','Buyer fees USD','Collected seller fees USD','Fees owed USD','Refund USD','Net USD','Payout USD') if locale == 'en' else ('الطلب','الإجمالي بالدولار','رسوم المشتري بالدولار','رسوم البائع المحصلة بالدولار','الرسوم المستحقة بالدولار','المبلغ المسترد بالدولار','الصافي بالدولار','المبلغ المدفوع بالدولار')
    output = io.StringIO(newline='')
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    designation = 'Simulated receipt' if locale == 'en' else 'إيصال محاكاة'
    writer.writerow((*headers, 'Result type' if locale == 'en' else 'نوع النتيجة'))
    for row in answer['items']:
        cells = []
        for key in columns:
            value = row[key]
            if key != 'order_id':
                integer(value, -MAX_MINOR)
                value = ('-' if value < 0 else '') + f'{abs(value)//100}.{abs(value)%100:02d}'
            else:
                value = str(value)
                if value.lstrip().startswith(('=','+','-','@')) or any(ord(char) < 32 for char in value):
                    value = "'" + value
            cells.append(value)
        writer.writerow((*cells, designation))
    content = ('\ufeff' + output.getvalue()).encode('utf-8')
    if len(content) > 1048576:
        raise ValueError('export_too_large')
    return content
