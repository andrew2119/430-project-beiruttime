"""Durable private synthetic outbox. No external delivery transport exists."""
import asyncio
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5, NAMESPACE_URL
from pathlib import Path
from .templates import render


class Rejected(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def utc(value):
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise Rejected('unavailable', 503)
    return value


class Outbox:
    def __init__(self, path, provider, clock=lambda: datetime.now(timezone.utc)):
        self.path, self.provider, self.clock = path, provider, clock
        with self.connection() as db:
            db.execute((Path(__file__).parent / 'migrations/L22_0001_email.sql').read_text())

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=1, isolation_level=None)
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

    async def authority(self, command, actor, organization):
        if str(command.actor_id) != str(actor) or command.organization_id != organization:
            raise Rejected('denied', 403)
        try:
            current = await asyncio.wait_for(self.provider(command, actor, organization), 2)
        except Exception:
            raise Rejected('unavailable', 503) from None
        return self.validate_authority(current, command, actor, organization)

    def validate_authority(self, current, command, actor, organization):
        now = utc(self.clock())
        if not current.permitted or current.actor_id != command.actor_id or current.organization_id != organization:
            raise Rejected('denied', 403)
        if current.subject_id != command.subject_id or current.watch_id != command.watch_id or current.event_id != command.event_id:
            raise Rejected('denied', 403)
        if current.verified_revision != current.recipient_revision or current.recipient_revision != command.recipient_revision:
            raise Rejected('recipient_unverified', 403)
        if (current.revision, current.quote_id, current.quote_revision, current.policy_revision, current.kind) != (
            command.expected_revision, command.quote_id, command.quote_revision, command.policy_revision, command.kind):
            raise Rejected('stale_revision')
        if utc(current.occurred_at) > now or now >= utc(current.valid_until):
            raise Rejected('stale_revision')
        return current

    async def admit(self, command, actor, organization, action):
        if command.actor_id != actor or command.organization_id != organization:
            raise Rejected('denied', 403)
        active, called, completed, receipt = True, False, False, None

        def commit(current):
            nonlocal called, completed, receipt
            if not active or called:
                raise Rejected('unavailable', 503)
            called = True
            self.validate_authority(current, command, actor, organization)
            receipt = action(current)
            completed = True
            return receipt

        try:
            await asyncio.wait_for(self.provider.admit(command, actor, organization, commit), 2)
            if not completed:
                raise Rejected('unavailable', 503)
            return receipt
        except Rejected:
            raise
        except Exception:
            raise Rejected('unavailable', 503) from None
        finally:
            active = False

    @staticmethod
    def result(row):
        command = json.loads(row['command'])
        return {key: command[key] for key in ('schema_version', 'operation_id', 'subject_id', 'watch_id',
                'actor_id', 'organization_id', 'expected_revision', 'locale', 'kind')} | {
            'revision': {'captured': 1, 'possibly_sent': 2, 'recorded': 3, 'failed': 3}[row['state']],
            'state': row['state'], 'attempt_id': row['attempt'], 'synthetic': True,
            'pending_reason': 'delivery_unknown' if row['state'] == 'possibly_sent' else None,
            'next_actor': json.loads(row['content'])['support_actor_id'] if row['state'] in ('possibly_sent', 'failed') else command['actor_id'],
            'next_review_at': row['review'], 'available_at': row['available'],
            'authenticated_link': '/' + command['locale'] + '/notification-email?operation_id=' + row['operation']}

    async def capture(self, command, actor, organization):
        return await self.admit(command, actor, organization,
                                lambda current: self.capture_admitted(command, actor, organization, current))

    def capture_admitted(self, command, actor, organization, current):
        encoded = command.model_dump_json()
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connection() as db:
            if utc(self.clock()) >= utc(current.valid_until):
                raise Rejected('stale_revision')
            prior = db.execute('SELECT * FROM l22_email WHERE operation=? OR (actor=? AND organization=? AND event=?)',
                (str(command.operation_id), str(actor), str(organization), str(command.event_id))).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise Rejected('operation_conflict')
                return self.result(prior)
            available = utc(self.clock()).isoformat()
            link = '/' + command.locale + '/notification-email?operation_id=' + str(command.operation_id)
            content = json.dumps({'template_version': 1, 'message': render({'locale': command.locale, 'kind': command.kind, 'authenticated_link': link}),
                'support_actor_id': str(current.support_actor_id), 'verified_recipient_id': str(actor), 'verified_revision': current.verified_revision,
                'verification_recorded_at': available, 'source_occurred_at': current.occurred_at.isoformat()})
            db.execute('INSERT INTO l22_email VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (str(command.operation_id), str(actor), str(organization), str(command.event_id), fingerprint,
                 encoded, command.recipient_revision, 'captured', None, available, None, content, str(command.subject_id)))
            return self.result(db.execute('SELECT * FROM l22_email WHERE operation=?', (str(command.operation_id),)).fetchone())

    async def current_row(self, operation, actor, organization, command_type):
        with self.connection() as db:
            row = db.execute('SELECT * FROM l22_email WHERE operation=? AND actor=? AND organization=?',
                (str(operation), str(actor), str(organization))).fetchone()
        if row is None:
            raise Rejected('not_found', 404)
        command = command_type.model_validate_json(row['command'])
        current = await self.authority(command, actor, organization)
        return row, current

    async def lookup(self, operation, actor, organization, command_type):
        row, _ = await self.current_row(operation, actor, organization, command_type)
        return self.result(row)

    async def listing(self, actor, organization, command_type, offset=0, limit=20):
        if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 100000 or not 1 <= limit <= 50:
            raise Rejected('invalid_page', 422)
        try:
            scope = await asyncio.wait_for(self.provider.scope(actor, organization), 2)
            subjects = scope.subject_ids
            if len(subjects) > 10000 or not all(isinstance(subject, UUID) for subject in subjects):
                raise ValueError('invalid_scope')
        except Exception:
            raise Rejected('unavailable', 503) from None
        if not scope.permitted or scope.actor_id != actor or scope.organization_id != organization:
            raise Rejected('denied', 403)
        with self.connection() as db:
            db.execute('CREATE TEMP TABLE current_subjects (subject TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO current_subjects VALUES (?)', ((str(subject),) for subject in subjects))
            total = db.execute('SELECT count(*) FROM l22_email e JOIN current_subjects s ON s.subject=e.subject WHERE actor=? AND organization=?',
                (str(actor), str(organization))).fetchone()[0]
            rows = db.execute('SELECT e.* FROM l22_email e JOIN current_subjects s ON s.subject=e.subject WHERE actor=? AND organization=? ORDER BY available DESC,operation DESC LIMIT ? OFFSET ?',
                (str(actor), str(organization), limit, offset)).fetchall()
        # A bounded page checks authority concurrently under a single dependency budget.
        async def check(row):
            await self.authority(command_type.model_validate_json(row['command']), actor, organization)
            return self.result(row)
        items = await asyncio.gather(*(check(row) for row in rows))
        return {'items': items, 'total': total, 'offset': offset, 'limit': limit}

    async def attempt(self, operation, actor, organization, command_type, outcome='recorded'):
        if outcome not in ('recorded', 'failed', 'possibly_sent'):
            raise Rejected('invalid_outcome', 422)
        row, _ = await self.current_row(operation, actor, organization, command_type)
        command = command_type.model_validate_json(row['command'])
        return await self.admit(command, actor, organization,
                                lambda current: self.attempt_admitted(operation, current, outcome))

    def attempt_admitted(self, operation, current, outcome):
        with self.connection() as db:
            if utc(self.clock()) >= utc(current.valid_until):
                raise Rejected('stale_revision')
            row = db.execute('SELECT * FROM l22_email WHERE operation=?', (str(operation),)).fetchone()
            if row['state'] != 'captured':
                return self.result(row)
            attempt = str(uuid5(NAMESPACE_URL, 'transaction-email.v1:' + str(operation)))
            review = (utc(self.clock()) + timedelta(hours=24)).isoformat()
            db.execute("UPDATE l22_email SET state='possibly_sent',attempt=?,review=? WHERE operation=?", (attempt, review, str(operation)))
        # The uncertainty marker is committed before any result can be acknowledged.
        # This synthetic transition performs no network operation.
        with self.connection() as db:
            db.execute('UPDATE l22_email SET state=?,review=? WHERE operation=?',
                (outcome, review if outcome != 'recorded' else None, str(operation)))
            return self.result(db.execute('SELECT * FROM l22_email WHERE operation=?', (str(operation),)).fetchone())

    async def destination(self, operation, actor, organization, command_type):
        _, current = await self.current_row(operation, actor, organization, command_type)
        if current.destination not in ('checkout', 'prices', 'inbox') or not isinstance(current.destination_id, UUID):
            raise Rejected('unavailable', 503)
        return {'url': '/' + current.destination + ('' if current.destination == 'inbox' else '/' + str(current.destination_id))}
