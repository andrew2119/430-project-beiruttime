"""Serialized private return records and durable refund handoffs."""
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

class Returns:
    def __init__(self, path, source):
        self.source = source
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS l19_returns(subject TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l19_operations(id TEXT PRIMARY KEY, command TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l19_outbox(subject TEXT PRIMARY KEY, body TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def _current(self, actor, organization, subject):
        try:
            facts = self.source(actor, organization, subject, timeout_seconds=2)
        except (TimeoutError, ConnectionError):
            raise ValueError('unavailable') from None
        if not facts or not facts['authorized'] or facts['organization_id'] != organization or facts['subject_id'] != subject or facts['actor_id'] != actor:
            raise ValueError('denied')
        return facts

    def current(self, actor, organization, subject):
        self._current(actor, organization, subject)
        row = self.db.execute('SELECT body FROM l19_returns WHERE subject=?', (subject,)).fetchone()
        return json.loads(row[0]) if row else None

    def lookup(self, operation_id, actor, organization, subject):
        self._current(actor, organization, subject)
        row = self.db.execute('SELECT command,result FROM l19_operations WHERE id=?', (operation_id,)).fetchone()
        if not row:
            return None
        command = json.loads(row[0])
        if (command['actor_id'], command['organization_id'], command['subject_id']) != (actor, organization, subject):
            raise ValueError('denied')
        return json.loads(row[1])

    def execute(self, command):
        command.validate()
        values = asdict(command)
        if len(json.dumps(values)) > 4096:
            raise ValueError('invalid')
        encoded = json.dumps(values, sort_keys=True)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            f = self._current(command.actor_id, command.organization_id, command.subject_id)
            if command.watch_id != f['watch_id'] or command.policy_revision != f['policy_revision']:
                raise ValueError('denied')
            old = self.db.execute('SELECT command,result FROM l19_operations WHERE id=?', (command.operation_id,)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError('operation_conflict')
                self.db.execute('COMMIT')
                return json.loads(old[1])
            row = self.db.execute('SELECT body FROM l19_returns WHERE subject=?', (command.subject_id,)).fetchone()
            previous = json.loads(row[0]) if row else None
            bindings = {key: f[key] for key in ('watch_id','watch_revision','buyer_id','organization_id','quote_id','quote_revision','policy_revision','principal_minor','currency')}
            if previous and previous['bindings'] != bindings:
                raise ValueError('stale_source')
            revision = previous['revision'] if previous else 0
            if revision != command.expected_revision or f['revision'] != command.source_revision:
                raise ValueError('stale_revision')
            state = previous['state'] if previous else None
            allowed = {'request': (None,), 'permit': ('requested',), 'decline': ('requested',), 'receive': ('permitted','unresolved'), 'refund_pending': ('received',), 'refunded': ('received','refund_pending')}
            if command.kind not in allowed or state not in allowed[command.kind]:
                raise ValueError('invalid_transition')
            if command.kind == 'request':
                if command.actor_id != f['buyer_id'] or not f['paid_held']:
                    raise ValueError('denied')
                state = 'requested'
            elif command.kind in ('permit','decline'):
                if not f['assigned_reviewer'] or command.actor_id == f['buyer_id']:
                    raise ValueError('denied')
                state = 'permitted' if command.kind == 'permit' else 'declined'
            elif command.kind == 'receive':
                if not f['assigned_intake']:
                    raise ValueError('denied')
                r = f.get('receipt')
                complete = bool(r and r['receipt_id'] == command.receipt_id and r['order_id'] == command.subject_id and r['watch_id'] == command.watch_id and r['watch_revision'] == f['watch_revision'] and r['authorized_recipient'] == command.actor_id and r['to_actor'] == command.actor_id and r['from_actor'] and r['condition'] and r['location'] and r['proof_revision'] and not r['incident_revision'] and set(r['accessories']) == set(f['accessories']))
                if complete:
                    instant = datetime.fromisoformat(r['received_at'].replace('Z','+00:00'))
                    now = datetime.fromisoformat(f['now'].replace('Z','+00:00'))
                    complete = instant.utcoffset() == timezone.utc.utcoffset(instant) and now.utcoffset() == timezone.utc.utcoffset(now) and instant <= now
                state = 'received' if complete else 'unresolved'
            else:
                if not f['financial_producer'] or f['refund_state'] != command.kind or f['refund_return_operation'] != previous['receipt_operation_id']:
                    raise ValueError('denied')
                state = command.kind
            principal = f['principal_minor']
            if type(principal) is not int or not 0 < principal <= 9007199254740991 or f['currency'] != 'USD':
                raise ValueError('invalid_economics')
            result = dict(bindings=bindings, reason=command.reason, source_revision=command.source_revision, receipt_id=command.receipt_id if command.kind == 'receive' else (previous or {}).get('receipt_id'), schema_version='orders.returns.v1', operation_id=command.operation_id, subject_id=command.subject_id, watch_id=command.watch_id, actor_id=command.actor_id, organization_id=command.organization_id, expected_revision=command.expected_revision, state=state, revision=revision+1, pending_reason='intake_mismatch' if state == 'unresolved' else None, next_actor=f['responsible_operator'], next_review_at=f['next_review_at'], receipt_operation_id=command.operation_id if state == 'received' else (previous or {}).get('receipt_operation_id'), policy_revision=command.policy_revision, quote_id=f['quote_id'])
            body = json.dumps(result)
            self.db.execute('INSERT OR REPLACE INTO l19_returns VALUES (?,?)', (command.subject_id,body))
            self.db.execute('INSERT INTO l19_operations VALUES (?,?,?)', (command.operation_id,encoded,body))
            if state == 'received':
                handoff = dict(schema_version='orders.return-received.v1', operation_id=command.operation_id, subject_id=command.subject_id, watch_id=command.watch_id, quote_id=f['quote_id'], quote_revision=f['quote_revision'], buyer_id=f['buyer_id'], organization_id=command.organization_id, source_revision=command.source_revision, return_revision=revision+1, policy_revision=command.policy_revision, currency='USD', maximum_principal_minor=principal, receipt_id=command.receipt_id)
                self.db.execute('INSERT INTO l19_outbox VALUES (?,?)', (command.subject_id,json.dumps(handoff)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
