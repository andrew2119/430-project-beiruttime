"""Bounded consent commands over current source facts and durable local receipts."""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Protocol, ContextManager
from uuid import UUID
from bt_contracts.service.finish.v1 import Command, Snapshot

class Refusal(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class Provider(Protocol):
    def current(self, actor: UUID, subject: UUID, timeout: float) -> ContextManager[Snapshot]:
        """Authenticate and serialize current membership, assignment and source facts.

        Hold the source revision fence through the local transaction commit.
        Never return cached authority. Deadline includes acquisition and body read.
        """
        ...

class ConsentService:
    def __init__(self, connection, provider: Provider, clock=lambda: datetime.now(timezone.utc)):
        self.db, self.provider, self.clock = connection, provider, clock

    def _authority(self, actor, facts, now):
        if now.tzinfo is None or now.utcoffset() is None:
            raise Refusal('unavailable')
        if actor != facts.buyer_id or not facts.current or not facts.assigned:
            raise Refusal('denied')
        if not facts.retained or now >= facts.valid_until:
            raise Refusal('stale')

    def submit(self, actor: UUID, command: Command):
        if actor != command.actor_id:
            raise Refusal('denied')
        try:
            with self.provider.current(actor, command.subject_id, timeout=2.0) as facts:
                self._authority(actor, facts, self.clock())
                for key in ('subject_id', 'watch_id', 'organization_id', 'source_revision',
                            'assessment_revision', 'quote_id', 'quote_revision', 'policy_revision'):
                    if getattr(command, key) != getattr(facts, key):
                        raise Refusal('stale')
                encoded = command.model_dump_json()
                self.db.execute('PRAGMA busy_timeout=250')
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    old = self.db.execute('SELECT request, response FROM finish_receipts WHERE operation_id=?',
                                          (str(command.operation_id),)).fetchone()
                    if old:
                        if old[0] != encoded:
                            raise Refusal('conflict')
                        self._authority(actor, facts, self.clock())
                        self.db.commit()
                        return json.loads(old[1])
                    row = self.db.execute('SELECT revision FROM finish_consents WHERE subject_id=?',
                                          (str(command.subject_id),)).fetchone()
                    revision = row[0] if row else 0
                    if command.expected_revision != revision:
                        raise Refusal('stale')
                    choices = {x.area_id: x.decision for x in command.choices}
                    if choices.keys() != {x.area_id for x in facts.areas}:
                        raise Refusal('scope_mismatch')
                    for area in facts.areas:
                        if choices[area.area_id] == 'no_polish':
                            continue
                        unsafe = (not area.suitable or not area.material_known or not area.preservation_assessed or area.original == 'unknown'
                                  or area.coating != 'absent' or area.plating != 'absent'
                                  or area.engraving != 'absent')
                        action_matches = ((area.assessed_action == 'brush' and area.desired == 'brushed')
                                          or (area.assessed_action == 'polish' and area.desired == 'mirror'))
                        if unsafe or not action_matches:
                            raise Refusal('unsuitable')
                    result = self._result(command, revision + 1, 'recorded')
                    response = json.dumps(result, sort_keys=True)
                    self.db.execute('INSERT INTO finish_consents VALUES(?,?,?,?) ON CONFLICT(subject_id) DO UPDATE SET revision=excluded.revision, request=excluded.request, source_snapshot=excluded.source_snapshot',
                                    (str(command.subject_id), revision + 1, encoded, facts.model_dump_json()))
                    self.db.execute('INSERT INTO finish_receipts VALUES(?,?,?,?)',
                                    (str(command.operation_id), encoded, response, facts.model_dump_json()))
                    # Only non-private references leave the module; publication retries by event id.
                    self.db.execute('INSERT INTO finish_outbox VALUES(?,?,?)',
                                    (str(command.operation_id), 'finish.consent-recorded.v1', response))
                    self._authority(actor, facts, self.clock())
                    self.db.commit()
                    return result
                except BaseException:
                    self.db.rollback()
                    raise
        except sqlite3.OperationalError:
            return self._result(command, command.expected_revision, 'pending')
        except (TimeoutError, ConnectionError):
            return self._result(command, command.expected_revision, 'pending')

    def detail(self, actor: UUID, subject: UUID):
        try:
            with self.provider.current(actor, subject, timeout=2.0) as facts:
                self._authority(actor, facts, self.clock())
                if facts.subject_id != subject:
                    raise Refusal('denied')
                row = self.db.execute('SELECT revision,request FROM finish_consents WHERE subject_id=?', (str(subject),)).fetchone()
                revision, choices = 0, []
                if row:
                    revision = row[0]
                    command = Command.model_validate_json(row[1])
                    if command.actor_id != actor or command.organization_id != facts.organization_id:
                        raise Refusal('denied')
                    if all(getattr(command, key) == getattr(facts, key) for key in
                           ('watch_id', 'source_revision', 'assessment_revision', 'quote_id', 'quote_revision', 'policy_revision')):
                        choices = [choice.model_dump(mode='json') for choice in command.choices]
                return {'source': facts.model_dump(mode='json'), 'revision': revision, 'choices': choices}
        except (TimeoutError, ConnectionError):
            raise Refusal('unavailable') from None

    def lookup(self, actor: UUID, subject: UUID, operation: UUID):
        try:
            with self.provider.current(actor, subject, timeout=2.0) as facts:
                self._authority(actor, facts, self.clock())
                row = self.db.execute('SELECT request,response FROM finish_receipts WHERE operation_id=?', (str(operation),)).fetchone()
                if not row:
                    raise Refusal('not_found')
                command = Command.model_validate_json(row[0])
                if command.subject_id != subject or command.actor_id != actor or command.organization_id != facts.organization_id:
                    raise Refusal('denied')
                return json.loads(row[1])
        except (TimeoutError, ConnectionError):
            raise Refusal('unavailable') from None

    @staticmethod
    def _result(command, revision, state):
        return {'schema_version': 'finish.v1', 'operation_id': str(command.operation_id),
                'subject_id': str(command.subject_id), 'watch_id': str(command.watch_id),
                'actor_id': str(command.actor_id), 'organization_id': str(command.organization_id),
                'expected_revision': command.expected_revision, 'revision': revision, 'state': state,
                'pending_reason': 'source_unavailable' if state == 'pending' else None,
                'next_actor': 'buyer' if state == 'pending' else None, 'next_review_at': None}
