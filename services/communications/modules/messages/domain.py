"""Private conversations with durable serialized receipts and restricted projections."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

VERSION = 'communications.messages.v1'
CONTACT = re.compile(r'[\w.+-]+\s*[@＠]\s*[\w.-]+\.[a-zA-Z]{2,}|(?:\+?[\d٠-٩۰-۹][\s().-]*){7,}|(?:https?://|www\.)\S+|\b[\w.+-]+\s+(?:at|AT)\s+[\w.-]+\s+(?:dot|DOT)\s+\w+', re.UNICODE)


class Denied(Exception):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__(code)


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('utc_required')
    return parsed.astimezone(timezone.utc)


def bounded(value, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Denied('invalid_request', 422)
    return value


def integer(value, minimum=0, maximum=2**53-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Denied('invalid_request', 422)
    return value


class Store:
    """A service-owned connection per transaction; no shared service tables.

    The composition owner supplies a persistent file and current source authority.
    Acknowledgement follows commit, including the private invalidation outbox.
    """
    def __init__(self, path):
        self.path = str(Path(path))
        with self.tx() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS l22_threads(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS l22_members(thread TEXT, actor TEXT, joined TEXT, left_at TEXT, organization TEXT,
                    PRIMARY KEY(thread,actor,joined));
                CREATE TABLE IF NOT EXISTS l22_messages(thread TEXT, sequence INTEGER, actor TEXT,
                    body TEXT, sent TEXT, PRIMARY KEY(thread,sequence));
                CREATE TABLE IF NOT EXISTS l22_receipts(thread TEXT, actor TEXT, operation TEXT,
                    digest TEXT, result TEXT, organization TEXT, kind TEXT, PRIMARY KEY(thread,actor,operation));
                CREATE TABLE IF NOT EXISTS l22_blocks(thread TEXT, actor TEXT, target TEXT,
                    PRIMARY KEY(thread,actor,target));
                CREATE TABLE IF NOT EXISTS l22_markers(thread TEXT, actor TEXT, sequence INTEGER,
                    PRIMARY KEY(thread,actor));
                CREATE TABLE IF NOT EXISTS l22_reports(id INTEGER PRIMARY KEY, thread TEXT, actor TEXT,
                    sequence INTEGER, kind TEXT, reason TEXT, state TEXT DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS l22_delivery(thread TEXT, actor TEXT, value TEXT, saved TEXT NOT NULL,
                    PRIMARY KEY(thread,actor));
                CREATE TABLE IF NOT EXISTS l22_outbox(id INTEGER PRIMARY KEY, event TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0);
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(l22_receipts)')}
            if 'kind' not in columns:
                db.execute('ALTER TABLE l22_receipts ADD COLUMN kind TEXT')
            if 'organization' not in columns:
                db.execute('ALTER TABLE l22_receipts ADD COLUMN organization TEXT')

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def provision(self, snapshot):
        """Internal only: trusted source provides scope, intervals and original work.

        This is also the membership replacement boundary after current source checks.
        No browser-supplied participant or support flag is accepted.
        """
        data = {key: snapshot[key] for key in ('id', 'kind', 'subject_id', 'watch_id', 'organization_id',
                'source_revision', 'quote_revision', 'policy_revision', 'original_work_id',
                'active_support', 'paid_held')}
        if data['kind'] not in ('listing', 'order', 'business'):
            raise Denied('invalid_request', 422)
        for key in ('id', 'subject_id', 'watch_id'):
            bounded(data[key])
        integer(data['source_revision'], 1)
        integer(data['policy_revision'], 1)
        if data['quote_revision'] is not None:
            integer(data['quote_revision'], 1)
        if type(data['active_support']) is not bool or type(data['paid_held']) is not bool:
            raise Denied('invalid_request', 422)
        members = snapshot['members']
        if not 1 <= len(members) <= 50:
            raise Denied('invalid_request', 422)
        for member in members:
            bounded(member['actor_id'])
            start = instant(member['joined_at'])
            if member['left_at'] is not None and instant(member['left_at']) <= start:
                raise Denied('invalid_request', 422)
        with self.tx() as db:
            old = db.execute('SELECT data FROM l22_threads WHERE id=?', (data['id'],)).fetchone()
            previous = json.loads(old['data']) if old else None
            if previous and data['source_revision'] < previous['source_revision']:
                raise Denied('revision', 409)
            if previous and any(data[key] != previous[key] for key in ('kind', 'subject_id', 'watch_id', 'organization_id', 'original_work_id')):
                raise Denied('scope')
            data['revision'] = previous['revision'] if previous else 1
            old_members = [dict(row) for row in db.execute('SELECT actor,joined,left_at,organization FROM l22_members WHERE thread=? ORDER BY actor,joined', (data['id'],))]
            new_members = sorted([{'actor': m['actor_id'], 'joined': instant(m['joined_at']).isoformat(), 'left_at': instant(m['left_at']).isoformat() if m['left_at'] else None, 'organization': m.get('organization_id')} for m in members], key=lambda m: (m['actor'], m['joined']))
            if previous and (data != previous or old_members != new_members):
                data['revision'] += 1
            db.execute('INSERT OR REPLACE INTO l22_threads VALUES(?,?)', (data['id'], json.dumps(data)))
            db.execute('DELETE FROM l22_members WHERE thread=?', (data['id'],))
            for member in members:
                db.execute('INSERT INTO l22_members VALUES(?,?,?,?,?)', (data['id'], member['actor_id'],
                           instant(member['joined_at']).isoformat(), instant(member['left_at']).isoformat() if member['left_at'] else None, member.get('organization_id')))
        return data

    def _access(self, db, thread_id, actor, organization, facts, now):
        row = db.execute('SELECT data FROM l22_threads WHERE id=?', (thread_id,)).fetchone()
        if row is None:
            raise Denied('membership')
        thread = json.loads(row['data'])
        # Current facts must come from the owning provider, never a projection.
        if not isinstance(facts, dict):
            raise Denied('source_unavailable', 503)
        if not facts or facts.get('state') != 'authorized':
            raise Denied('source_unavailable' if not facts or facts.get('state') == 'unavailable' else 'scope',
                         503 if not facts or facts.get('state') == 'unavailable' else 403)
        bindings = {'actor_id': actor, 'organization_id': organization, 'thread_id': thread_id,
                    'subject_id': thread['subject_id'], 'watch_id': thread['watch_id']}
        if any(facts.get(key) != value for key, value in bindings.items()) or facts.get('subject_organization_id') != thread['organization_id']:
            raise Denied('scope')
        if any(facts.get(key) != thread[key] for key in ('source_revision', 'quote_revision', 'policy_revision', 'paid_held', 'active_support')):
            raise Denied('source_revision', 409)
        members = db.execute('SELECT * FROM l22_members WHERE thread=? AND actor=?', (thread_id, actor)).fetchall()
        current = [m for m in members if instant(m['joined']) <= now and (m['left_at'] is None or now < instant(m['left_at']))]
        if len(current) != 1 or facts.get('current_member') is not True or current[0]['organization'] != organization:
            raise Denied('membership')
        return thread, current[0]

    def read(self, thread_id, actor, organization, facts, now, cursor=0, limit=20):
        integer(cursor)
        integer(limit, 1, 50)
        with self.tx() as db:
            thread, member = self._access(db, thread_id, actor, organization, facts, now)
            # Both directions of an ordinary block deny access. Support has its own assigned channel.
            blocks = self._blocks(db, thread_id)
            if not thread['active_support'] and any(actor in pair for pair in blocks):
                raise Denied('blocked')
            start = member['joined']
            total = db.execute('SELECT COUNT(*) FROM l22_messages WHERE thread=? AND sent>=?', (thread_id, start)).fetchone()[0]
            marker = db.execute('SELECT sequence FROM l22_markers WHERE thread=? AND actor=?', (thread_id, actor)).fetchone()
            unread = db.execute('SELECT COUNT(*) FROM l22_messages WHERE thread=? AND sent>=? AND actor<>? AND sequence>?',
                                (thread_id, start, actor, marker['sequence'] if marker else 0)).fetchone()[0]
            rows = db.execute('SELECT * FROM l22_messages WHERE thread=? AND sent>=? AND sequence>? ORDER BY sequence LIMIT ?',
                              (thread_id, start, cursor, limit+1)).fetchall()
            page = rows[:limit]
            items = [{'sequence': r['sequence'], 'actor_id': r['actor'], 'body': r['body'], 'sent_at': r['sent'],
                      'preview': CONTACT.sub('•••', r['body']) if not thread['paid_held'] else '',
                      'correction_required': bool(CONTACT.search(r['body'])) and not thread['paid_held']} for r in page]
            return {'thread': thread, 'items': items, 'total': total,
                    'next_cursor': page[-1]['sequence'] if page and len(rows) > limit else None,
                    'unread': unread,
                    'blocked': [b['target'] for b in blocks if b['actor'] == actor]}

    def _blocks(self, db, thread):
        return db.execute('SELECT actor,target FROM l22_blocks WHERE thread=?', (thread,)).fetchall()

    def lookup(self, thread, actor, organization, facts, now, operation):
        bounded(operation)
        with self.tx() as db:
            current, _ = self._access(db, thread, actor, organization, facts, now)
            row = db.execute('SELECT result,organization,kind FROM l22_receipts WHERE thread=? AND actor=? AND operation=?', (thread, actor, operation)).fetchone()
            if not current['active_support'] and any(actor in pair for pair in self._blocks(db, thread)) and (not row or row['kind'] != 'block'):
                raise Denied('blocked')
            if row and row['organization'] != json.dumps(organization):
                raise Denied('operation_conflict', 409)
            return json.loads(row['result']) if row else {'schema_version': VERSION, 'operation_id': operation, 'state': 'pending', 'pending_reason': 'not_recorded'}

    def command(self, thread_id, actor, organization, facts, now, body):
        if not isinstance(body, dict) or set(body) - {'operation_id', 'expected_revision', 'source_revision', 'quote_revision', 'policy_revision', 'kind', 'body', 'target', 'sequence'}:
            raise Denied('invalid_request', 422)
        operation = bounded(body.get('operation_id'))
        kind = body.get('kind')
        if kind not in ('send', 'read', 'block', 'unblock', 'report', 'appeal', 'delivery'):
            raise Denied('invalid_request', 422)
        integer(body.get('expected_revision'), 1)
        integer(body.get('source_revision'), 1)
        integer(body.get('policy_revision'), 1)
        if 'quote_revision' not in body:
            raise Denied('invalid_request', 422)
        if body['quote_revision'] is not None:
            integer(body['quote_revision'], 1)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.tx() as db:
            thread, member = self._access(db, thread_id, actor, organization, facts, now)
            blocks = self._blocks(db, thread_id)
            prior = db.execute('SELECT * FROM l22_receipts WHERE thread=? AND actor=? AND operation=?', (thread_id, actor, operation)).fetchone()
            block_retry = prior is not None and prior['kind'] == kind == 'block'
            if not thread['active_support'] and kind not in ('unblock', 'report', 'appeal') and not block_retry and any(actor in pair for pair in blocks):
                raise Denied('blocked')
            if prior:
                if prior['organization'] != json.dumps(organization) or prior['digest'] != digest:
                    raise Denied('operation_conflict', 409)
                return json.loads(prior['result'])
            if any(body.get(k) != thread[k] for k in ('source_revision', 'quote_revision', 'policy_revision')) or body['expected_revision'] != thread['revision']:
                raise Denied('revision', 409)
            sequence = None
            if kind == 'send':
                text = bounded(body.get('body'), 4000)
                sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM l22_messages WHERE thread=?', (thread_id,)).fetchone()[0]
                db.execute('INSERT INTO l22_messages VALUES(?,?,?,?,?)', (thread_id, sequence, actor, text, now.isoformat()))
            elif kind == 'read':
                sequence = integer(body.get('sequence'))
                row = db.execute('SELECT sent FROM l22_messages WHERE thread=? AND sequence=?', (thread_id, sequence)).fetchone()
                if sequence and (not row or instant(row['sent']) < instant(member['joined'])):
                    raise Denied('membership')
                db.execute('INSERT INTO l22_markers VALUES(?,?,?) ON CONFLICT(thread,actor) DO UPDATE SET sequence=MAX(sequence,excluded.sequence)', (thread_id, actor, sequence))
            elif kind in ('block', 'unblock'):
                target = bounded(body.get('target'))
                if target == actor or not db.execute('SELECT 1 FROM l22_members WHERE thread=? AND actor=?', (thread_id, target)).fetchone():
                    raise Denied('membership')
                if kind == 'block':
                    # No ordinary block may sever an active custody/support obligation.
                    if thread['active_support']:
                        raise Denied('support_required', 409)
                    db.execute('INSERT OR IGNORE INTO l22_blocks VALUES(?,?,?)', (thread_id, actor, target))
                else:
                    db.execute('DELETE FROM l22_blocks WHERE thread=? AND actor=? AND target=?', (thread_id, actor, target))
            elif kind in ('report', 'appeal'):
                sequence = integer(body.get('sequence'), 1)
                row = db.execute('SELECT sent FROM l22_messages WHERE thread=? AND sequence=?', (thread_id, sequence)).fetchone()
                if not row or instant(row['sent']) < instant(member['joined']):
                    raise Denied('membership')
                reason = bounded(body.get('body'), 1000)
                db.execute('INSERT INTO l22_reports(thread,actor,sequence,kind,reason) VALUES(?,?,?,?,?)', (thread_id, actor, sequence, kind, reason))
            elif kind == 'delivery':
                if not thread['paid_held']:
                    raise Denied('payment_required')
                db.execute('INSERT OR REPLACE INTO l22_delivery VALUES(?,?,?,?)', (thread_id, actor, bounded(body.get('body'), 500), now.isoformat()))
            thread['revision'] += 1
            result = {'schema_version': VERSION, 'operation_id': operation, 'state': 'accepted', 'revision': thread['revision']}
            if sequence is not None:
                result['sequence'] = sequence
            db.execute('UPDATE l22_threads SET data=? WHERE id=?', (json.dumps(thread), thread_id))
            db.execute('INSERT INTO l22_receipts(thread,actor,operation,digest,result,organization,kind) VALUES(?,?,?,?,?,?,?)', (thread_id, actor, operation, digest, json.dumps(result), json.dumps(organization), kind))
            # This envelope deliberately carries no private text or contact data.
            db.execute('INSERT INTO l22_outbox(event) VALUES(?)', (json.dumps({'schema_version': VERSION, 'thread_id': thread_id, 'revision': thread['revision'], 'kind': 'private_changed'}),))
            return result

    def delivery(self, thread_id, actor, organization, facts, now):
        with self.tx() as db:
            thread, member = self._access(db, thread_id, actor, organization, facts, now)
            if not thread['active_support'] and any(actor in pair for pair in self._blocks(db, thread_id)):
                raise Denied('blocked')
            if not thread['paid_held']:
                raise Denied('payment_required')
            rows = db.execute('SELECT actor,value,saved FROM l22_delivery WHERE thread=? AND saved>=?', (thread_id, member['joined'])).fetchall()
            visible = []
            for row in rows:
                intervals = db.execute('SELECT joined,left_at FROM l22_members WHERE thread=? AND actor=?', (thread_id, row['actor'])).fetchall()
                if any(instant(m['joined']) <= instant(row['saved']) and instant(m['joined']) <= now and (m['left_at'] is None or now < instant(m['left_at'])) for m in intervals):
                    visible.append({'actor': row['actor'], 'value': row['value']})
            return {'items': visible}

    def status(self, thread_id, actor, organization, facts, now):
        with self.tx() as db:
            thread, _ = self._access(db, thread_id, actor, organization, facts, now)
            return {'thread': thread, 'blocked': [row['target'] for row in self._blocks(db, thread_id) if row['actor'] == actor]}
