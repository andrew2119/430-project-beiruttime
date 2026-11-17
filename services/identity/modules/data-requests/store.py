"""Durable request coordination with atomic private outbox and inbox receipts."""
import json
import re
import sqlite3
from datetime import datetime, timedelta
from policy import DOMAINS, REASONS, instant, stamp

TOKEN = re.compile(r'^[a-zA-Z0-9_-]{1,96}$')


def token(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError('invalid')
    return value


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**53 - 1:
        raise ValueError('invalid')
    return value


class Store:
    def __init__(self, path, authority, responsible_operator, operator_authority=None):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.authority = authority
        self.responsible_operator = responsible_operator
        self.operator_authority = operator_authority or (lambda *args: False)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, scope TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, operation TEXT NOT NULL, domain TEXT NOT NULL, command_revision INTEGER NOT NULL DEFAULT 1, attempts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, operation TEXT NOT NULL, body TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def _scope(self, actor, subject, organization):
        token(actor)
        token(subject)
        if organization is not None:
            token(organization)
        if actor != subject or not self.authority(actor, subject, organization):
            raise ValueError('denied')
        return json.dumps([actor, subject, organization])

    def _load(self, operation, scope):
        row = self.db.execute('SELECT * FROM requests WHERE id=?', (token(operation),)).fetchone()
        if row is None or row['scope'] != scope:
            raise ValueError('denied')
        return json.loads(row['body'])

    def _save(self, body):
        self.db.execute('UPDATE requests SET body=? WHERE id=?', (json.dumps(body, sort_keys=True), body['operation_id']))

    def _atomic(self, action):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = action()
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def create(self, operation, actor, subject, organization, kind, expected_revision, now):
        scope = self._scope(actor, subject, organization)
        token(operation)
        instant(now)
        integer(expected_revision)
        if kind not in ('export', 'delete') or expected_revision != 0:
            raise ValueError('invalid')
        def action():
            old = self.db.execute('SELECT scope,body FROM requests WHERE id=?', (operation,)).fetchone()
            if old:
                body = json.loads(old['body'])
                if old['scope'] != scope or body['kind'] != kind:
                    raise ValueError('conflict')
                return body
            count = self.db.execute("SELECT count(*) FROM requests WHERE scope=? AND json_extract(body, '$.state') != 'complete'", (scope,)).fetchone()[0]
            if count >= 100:
                raise ValueError('limit')
            body = dict(schema_version='data-requests.v1', operation_id=operation, subject_id=subject,
                        actor_id=actor, organization_id=organization, watch_id=None, expected_revision=0,
                        kind=kind, revision=1, policy_revision='D31.v1', state='pending',
                        responsible_operator_id=token(self.responsible_operator(actor, subject, organization)),
                        support_due_at=stamp(now + timedelta(hours=24)), escalation_at=stamp(now + timedelta(hours=48)),
                        submitted_at=stamp(now), due_at=stamp(now + timedelta(days=7 if kind == 'export' else 30)),
                        pending_reason='domain_acknowledgements', next_action='await_domains', next_actor='domain', next_review_at=stamp(now + timedelta(hours=24)),
                        domains={}, export_available=False, export_expires_at=None)
            self.db.execute('INSERT INTO requests VALUES(?,?,?)', (operation, scope, json.dumps(body)))
            for domain in DOMAINS:
                self.db.execute('INSERT INTO outbox(id,operation,domain) VALUES(?,?,?)', (operation + ':' + domain, operation, domain))
            return body
        return self._public(self._atomic(action))

    def lookup(self, operation, actor, subject, organization, now):
        body = self._load(operation, self._scope(actor, subject, organization))
        instant(now)
        if body['export_expires_at'] and instant(now) >= parse(body['export_expires_at']):
            body['export_available'] = False
            if body.get('_files'):
                body.update(state='partial', next_actor='operator', pending_reason='file_cleanup', next_action='remove_export_files')
        return self._public(body)

    def page(self, actor, subject, organization, now, page=0, page_size=20):
        scope = self._scope(actor, subject, organization)
        integer(page)
        integer(page_size, 1)
        if page_size > 50 or page > 100000:
            raise ValueError('invalid')
        rows = self.db.execute('SELECT id FROM requests WHERE scope=? ORDER BY id LIMIT ? OFFSET ?', (scope, page_size, page * page_size)).fetchall()
        total = self.db.execute('SELECT count(*) FROM requests WHERE scope=?', (scope,)).fetchone()[0]
        return dict(items=[self.lookup(r['id'], actor, subject, organization, now) for r in rows], total=total, page=page, page_size=page_size)

    def dispatch(self, operation, actor, subject, organization):
        scope = self._scope(actor, subject, organization)
        def action():
            body = self._load(operation, scope)
            rows = self.db.execute('SELECT * FROM outbox WHERE operation=? AND attempts<5 ORDER BY domain LIMIT 9', (operation,)).fetchall()
            commands = []
            for row in rows:
                self.db.execute('UPDATE outbox SET attempts=attempts+1 WHERE id=?', (row['id'],))
                commands.append(dict(command_id=row['id'], operation_id=operation, domain=row['domain'],
                                     actor_id=actor, subject_id=subject, organization_id=organization,
                                     kind=body['kind'], expected_revision=row['command_revision'], policy_revision='D31.v1'))
            if self.db.execute('SELECT 1 FROM outbox WHERE operation=? AND attempts>=5', (operation,)).fetchone() and body['next_actor'] != 'operator':
                body.update(next_actor='operator', next_action='retry_domain')
                body['revision'] += 1
                self._save(body)
            return commands
        return self._atomic(action)

    def recover_dispatch(self, operation, actor, subject, organization, operator, expected_revision):
        scope = self._scope(actor, subject, organization)
        token(operator)
        integer(expected_revision, 1)
        def action():
            body = self._load(operation, scope)
            if operator != body['responsible_operator_id'] or not self.operator_authority(operator, subject, organization):
                raise ValueError('denied')
            if body['revision'] != expected_revision:
                raise ValueError('stale')
            changed = self.db.execute('UPDATE outbox SET attempts=0 WHERE operation=? AND attempts>=5', (operation,)).rowcount
            if changed:
                body['revision'] += 1
                self._state(body)
                self._save(body)
            return body
        return self._public(self._atomic(action))

    def acknowledge(self, operation, actor, subject, organization, producer, receipt, now):
        scope = self._scope(actor, subject, organization)
        instant(now)
        required = {'receipt_id', 'domain', 'operation_id', 'expected_revision', 'source_revision', 'facts_revision', 'policy_revision', 'state', 'reasons', 'next_review_at', 'obligations_closed_at'}
        if set(receipt) != required or producer not in DOMAINS or receipt['domain'] != producer or receipt['operation_id'] != operation or receipt['policy_revision'] != 'D31.v1':
            raise ValueError('denied')
        token(receipt['receipt_id'])
        for field in ('expected_revision', 'source_revision', 'facts_revision'):
            integer(receipt[field], 1)
        reasons = receipt['reasons']
        if not isinstance(reasons, list) or len(reasons) > len(REASONS) or any(r not in REASONS for r in reasons) or len(set(reasons)) != len(reasons):
            raise ValueError('invalid')
        encoded = json.dumps(receipt, sort_keys=True)
        def action():
            body = self._load(operation, scope)
            old = self.db.execute('SELECT body,operation FROM inbox WHERE id=?', (receipt['receipt_id'],)).fetchone()
            if old:
                if old['body'] != encoded or old['operation'] != operation:
                    raise ValueError('conflict')
                return body
            command = self.db.execute('SELECT command_revision FROM outbox WHERE operation=? AND domain=?', (operation, producer)).fetchone()
            if command is None or command['command_revision'] != receipt['expected_revision']:
                raise ValueError('stale')
            previous = body['domains'].get(producer)
            if previous and (receipt['source_revision'] <= previous['source_revision'] or receipt['facts_revision'] < previous['facts_revision']):
                raise ValueError('stale')
            state = receipt['state']
            if state not in ('retained', 'failed', 'exported', 'deleted', 'redacted') or (body['kind'] == 'export' and state in ('deleted', 'redacted')) or (body['kind'] == 'delete' and state == 'exported'):
                raise ValueError('invalid')
            review = receipt['next_review_at']
            if state == 'retained':
                if not reasons or review is None or parse(review) <= now:
                    raise ValueError('invalid')
            elif reasons:
                raise ValueError('invalid')
            closed = receipt['obligations_closed_at']
            if closed is not None:
                closed_at = parse(closed)
                if closed_at > now:
                    raise ValueError('invalid')
                if body['kind'] == 'delete':
                    body['due_at'] = stamp(max(parse(body['due_at']), closed_at + timedelta(days=30)))
            if previous and previous['reasons'] and state != 'failed' and closed is None and (
                    state != 'retained' or not set(previous['reasons']).issubset(reasons)):
                raise ValueError('invalid')
            body['domains'][producer] = receipt.copy()
            if state == 'failed' and previous and previous['reasons']:
                body['domains'][producer].update(reasons=previous['reasons'], next_review_at=previous['next_review_at'])
            self.db.execute('INSERT INTO inbox VALUES(?,?,?)', (receipt['receipt_id'], operation, encoded))
            if state in ('deleted', 'redacted', 'exported'):
                self.db.execute('DELETE FROM outbox WHERE id=?', (operation + ':' + producer,))
            body['revision'] += 1
            self._state(body)
            self._save(body)
            return body
        return self._public(self._atomic(action))

    def _state(self, body):
        values = list(body['domains'].values())
        held = any(v['reasons'] for v in values)
        failed = any(v['state'] == 'failed' for v in values)
        all_done = len(values) == 9 and not held and not failed
        body['state'] = 'partial' if failed else 'held' if held else 'complete' if all_done and (body['kind'] == 'delete' or body['export_available']) else 'partial' if values else 'pending'
        body['pending_reason'] = None if body['state'] == 'complete' else 'obligations' if held else 'domain_acknowledgements'
        body['next_action'] = None if body['state'] == 'complete' else 'review_hold' if held else 'retry_domain' if failed else 'await_domains'
        body['next_actor'] = None if body['state'] == 'complete' else 'operator' if held or failed else 'domain'
        if self.db.execute('SELECT 1 FROM outbox WHERE operation=? AND attempts>=5', (body['operation_id'],)).fetchone():
            body.update(next_actor='operator', next_action='retry_domain')
        reviews = [v['next_review_at'] for v in values if v['reasons']]
        if reviews:
            body['next_review_at'] = stamp(min(parse(value) for value in [*reviews, body['support_due_at']]))
        elif body['state'] == 'complete':
            body['next_review_at'] = None

    def assemble(self, operation, actor, subject, organization, expected_revision, files, now):
        scope = self._scope(actor, subject, organization)
        instant(now)
        integer(expected_revision, 1)
        if not isinstance(files, list) or not 1 <= len(files) <= 20:
            raise ValueError('limit')
        for file in files:
            if set(file) != {'ref', 'size'}:
                raise ValueError('invalid')
            token(file['ref'])
            integer(file['size'], 1)
        if len({f['ref'] for f in files}) != len(files) or sum(f['size'] for f in files) > 25 * 1024 * 1024:
            raise ValueError('limit')
        def action():
            body = self._load(operation, scope)
            if body['revision'] != expected_revision:
                raise ValueError('stale')
            if body['kind'] != 'export' or len(body['domains']) != 9 or any(v['state'] != 'exported' for v in body['domains'].values()) or body['export_expires_at'] is not None:
                raise ValueError('conflict')
            body['_files'] = files
            body['export_expires_at'] = stamp(now + timedelta(hours=24))
            body['export_available'] = True
            body['revision'] += 1
            self._state(body)
            self._save(body)
            return body
        return self._public(self._atomic(action))

    def download_refs(self, operation, actor, subject, organization, now):
        body = self._load(operation, self._scope(actor, subject, organization))
        if not body['export_available'] or not body['export_expires_at'] or instant(now) >= parse(body['export_expires_at']):
            raise ValueError('denied')
        return body['_files']

    def expired_files(self, operation, actor, subject, organization, now):
        body = self._load(operation, self._scope(actor, subject, organization))
        if body['export_expires_at'] and instant(now) >= parse(body['export_expires_at']):
            return body.get('_files', [])
        return []

    def remove_file_ack(self, operation, actor, subject, organization, ref, removed, now):
        scope = self._scope(actor, subject, organization)
        if type(removed) is not bool:
            raise ValueError('invalid')
        def action():
            body = self._load(operation, scope)
            if not body['export_expires_at'] or instant(now) < parse(body['export_expires_at']):
                raise ValueError('invalid')
            files = body.get('_files', [])
            if ref in body.get('_removed_files', []):
                return body
            if ref not in [f['ref'] for f in files]:
                raise ValueError('denied')
            if removed:
                body.setdefault('_removed_files', []).append(ref)
                body['_files'] = [f for f in files if f['ref'] != ref]
            body['export_available'] = False
            self._state(body)
            if body['_files']:
                body.update(state='partial', next_actor='operator', pending_reason='file_cleanup', next_action='remove_export_files')
            elif all(v['state'] == 'exported' for v in body['domains'].values()) and len(body['domains']) == 9:
                body.update(state='complete', next_actor=None, pending_reason=None, next_action=None)
            body['revision'] += 1
            self._save(body)
            return body
        return self._public(self._atomic(action))

    @staticmethod
    def _public(body):
        public = {k: v for k, v in body.items() if not k.startswith('_')}
        public['domains'] = {domain: dict(state=value['state'], reasons=value['reasons']) for domain, value in body['domains'].items()}
        return public


def parse(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        instant(parsed)
        if stamp(parsed) != value:
            raise ValueError('invalid')
        return parsed
    except (TypeError, AttributeError, ValueError):
        raise ValueError('invalid') from None
