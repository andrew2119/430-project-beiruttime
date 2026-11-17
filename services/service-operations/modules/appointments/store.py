"""Durable isolated adapter; runtime database composition is supplied separately."""
import asyncio
import sqlite3
from contextlib import closing
from datetime import timedelta, timezone

from bt_contracts.service.appointments.v1 import Authority, Command, Visit
from .model import Rejected, authorize, resolve


class Store:
    def __init__(self, path, authority, clock):
        self.path, self.authority, self.clock = path, authority, clock
        with closing(self.connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS l20_p03_visits(id TEXT PRIMARY KEY, body TEXT NOT NULL,
                    organization_id TEXT NOT NULL, state TEXT NOT NULL, starts_at REAL NOT NULL, ends_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS l20_p03_slots
                    ON l20_p03_visits(organization_id, state, starts_at, ends_at);
                CREATE TABLE IF NOT EXISTS l20_p03_receipts(id TEXT PRIMARY KEY, command TEXT NOT NULL,
                    result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS l20_p03_outbox(operation_id TEXT PRIMARY KEY,
                    appointment_id TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=0.25)
        db.row_factory = sqlite3.Row
        return db

    async def current_authority(self, actor, subject, watch, organization):
        try:
            async with asyncio.timeout(1.2):
                result = Authority.model_validate(await self.authority(actor, subject, watch, organization))
        except Rejected:
            raise
        except (TimeoutError, ValueError, TypeError, OSError):
            raise Rejected('unavailable', 503) from None
        authorize(result, subject, watch, organization, actor)
        return result

    async def read(self, appointment_id, actor, organization, operation_id=None):
        with closing(self.connect()) as db:
            row = db.execute('SELECT body FROM l20_p03_visits WHERE id=?', (str(appointment_id),)).fetchone()
            if not row:
                raise Rejected('not_found', 404)
            visit = Visit.model_validate_json(row['body'])
            await self.current_authority(actor, visit.subject_id, visit.watch_id, organization)
            if visit.organization_id != organization:
                raise Rejected('denied', 403)
            if operation_id:
                receipt = db.execute('SELECT result FROM l20_p03_receipts WHERE id=?', (str(operation_id),)).fetchone()
                if not receipt:
                    raise Rejected('not_found', 404)
                result = Visit.model_validate_json(receipt['result'])
                if result.appointment_id != appointment_id or result.organization_id != organization or result.actor_id != actor:
                    raise Rejected('denied', 403)
                return result
            return visit

    async def execute(self, command: Command, authenticated_actor):
        if command.actor_id != authenticated_actor:
            raise Rejected('denied', 403)
        authority = await self.current_authority(command.actor_id, command.subject_id,
                                                 command.watch_id, command.organization_id)
        if command.purpose not in authority.purposes:
            raise Rejected('denied', 403)
        if command.kind == 'confirm' and authority.role != 'business':
            raise Rejected('denied', 403)
        if command.kind in ('request', 'reschedule') and authority.role != 'buyer':
            raise Rejected('denied', 403)
        encoded = command.model_dump_json()
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            receipt = db.execute('SELECT * FROM l20_p03_receipts WHERE id=?', (str(command.operation_id),)).fetchone()
            if receipt:
                if receipt['command'] != encoded:
                    raise Rejected('duplicate_conflict')
                return Visit.model_validate_json(receipt['result'])
            for name in ('source_revision', 'policy_revision', 'quote_id', 'quote_revision', 'assignment_revision'):
                if getattr(command, name) != getattr(authority, name):
                    raise Rejected('stale_revision')
            row = db.execute('SELECT body FROM l20_p03_visits WHERE id=?', (str(command.appointment_id),)).fetchone()
            prior = Visit.model_validate_json(row['body']) if row else None
            if command.kind == 'request':
                if prior:
                    raise Rejected('appointment_exists')
            else:
                if not prior:
                    raise Rejected('not_found', 404)
                if (prior.subject_id, prior.watch_id, prior.organization_id) != (
                        command.subject_id, command.watch_id, command.organization_id):
                    raise Rejected('denied', 403)
                if prior.revision != command.expected_revision:
                    raise Rejected('stale_revision')
                if prior.state == 'cancelled':
                    raise Rejected('cancelled')
            instant = resolve(command)
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() != timedelta(0):
                raise Rejected('unavailable', 503)
            if command.kind != 'cancel' and instant <= now:
                raise Rejected('elapsed')
            if command.kind in ('confirm', 'cancel'):
                fields = ('purpose', 'civil_time', 'duration_minutes', 'repeated_time_confirmed')
                if command.kind == 'confirm':
                    fields += ('source_revision', 'policy_revision', 'quote_id', 'quote_revision')
                if any(getattr(prior, name) != getattr(command, name) for name in fields) or prior.instant != instant:
                    raise Rejected('stale_revision')
            if command.kind == 'confirm':
                if prior.state != 'requested':
                    raise Rejected('confirmation_conflict')
                end = instant + timedelta(minutes=command.duration_minutes)
                overlap = db.execute("""SELECT id FROM l20_p03_visits
                    WHERE id<>? AND organization_id=? AND state='confirmed'
                    AND starts_at<? AND ends_at>? LIMIT 1""",
                    (str(command.appointment_id), str(command.organization_id), end.timestamp(), instant.timestamp())).fetchone()
                if overlap:
                    raise Rejected('slot_conflict')
            state = {'request': 'requested', 'reschedule': 'requested',
                     'confirm': 'confirmed', 'cancel': 'cancelled'}[command.kind]
            data = command.model_dump(exclude={'kind', 'selected_instant', 'assignment_revision'})
            if command.kind == 'cancel':
                for name in ('source_revision', 'policy_revision', 'quote_id', 'quote_revision'):
                    data[name] = getattr(prior, name)
            visit = Visit(**data, instant=instant.astimezone(timezone.utc), state=state,
                          revision=command.expected_revision + 1,
                          confirmed_by=command.actor_id if state == 'confirmed' else None,
                          assignment_revision=authority.assignment_revision,
                          pending_reason='business_confirmation' if state == 'requested' else None,
                          next_actor='business' if state == 'requested' else 'none',
                          next_review_at=now + timedelta(hours=24) if state == 'requested' else None)
            result = visit.model_dump_json()
            db.execute('INSERT OR REPLACE INTO l20_p03_visits VALUES (?,?,?,?,?,?)',
                       (str(visit.appointment_id), result, str(visit.organization_id), state, instant.timestamp(),
                        (instant + timedelta(minutes=visit.duration_minutes)).timestamp()))
            db.execute('INSERT INTO l20_p03_receipts VALUES (?,?,?)', (str(command.operation_id), encoded, result))
            db.execute('INSERT INTO l20_p03_outbox VALUES (?,?,?,?)',
                       (str(command.operation_id), str(visit.appointment_id), visit.revision, state))
            db.commit()
            return visit
        except sqlite3.Error:
            raise Rejected('unavailable', 503) from None
        finally:
            db.rollback()
            db.close()
