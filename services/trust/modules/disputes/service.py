"""Durable dispute intents; financial authority remains with Orders."""
import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from .contracts import Command


class Rejected(Exception):
    def __init__(self, code, closing_at=None):
        self.code, self.closing_at = code, closing_at
        super().__init__(code)


@dataclass(frozen=True)
class Source:
    subject_id: str
    watch_id: str
    buyer_id: str
    seller_id: str
    organization_id: str | None
    revision: int
    assignment_revision: int
    reviewer_id: str | None
    kind: str
    received_at: datetime
    receipt_id: str
    quote_id: str
    quote_revision: int
    policy_revision: int
    payment_revision: int
    principal_minor: int
    buyer_fee_minor: int
    business_fee_minor: int
    recipient_id: str
    ready: bool
    responsible_operator_id: str
    business_responders: tuple[str, ...] = ()


class Providers(Protocol):
    async def current(self, credential: str, subject: str, organization: str | None) -> tuple[str, Source]: ...
    async def evidence(self, credential: str, subject: str, evidence: list[dict]) -> bool: ...
    async def apply(self, binding: dict) -> dict: ...


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def instant(value):
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise Rejected('unavailable')
    return value


class Service:
    def __init__(self, database, providers: Providers, clock=lambda: datetime.now(timezone.utc)):
        self.database, self.providers, self.clock = database, providers, clock
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS l18_dispute_cases (
                    subject TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS l18_dispute_operations (
                    operation TEXT PRIMARY KEY, subject TEXT NOT NULL, actor TEXT NOT NULL,
                    request_hash TEXT NOT NULL, binding TEXT, body TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.database, timeout=1)
        db.row_factory = sqlite3.Row
        return db

    async def bounded(self, awaitable):
        try:
            return await asyncio.wait_for(awaitable, timeout=1.2)
        except (TimeoutError, OSError, ValueError, KeyError, TypeError):
            raise Rejected('unavailable') from None

    async def authority(self, credential, subject, organization):
        actor, source = await self.bounded(self.providers.current(credential, subject, organization))
        if source.subject_id != subject or source.organization_id != organization:
            raise Rejected('denied')
        if source.kind not in ('private_watch', 'business_watch', 'job'):
            raise Rejected('unavailable')
        money = (source.principal_minor, source.buyer_fee_minor, source.business_fee_minor)
        if any(type(x) is not int or not 0 <= x <= 9_007_199_254_740_991 for x in money):
            raise Rejected('unavailable')
        reviewer = actor == source.reviewer_id and actor not in (source.buyer_id, source.seller_id, *source.business_responders)
        if actor not in (source.buyer_id, source.seller_id, *source.business_responders) and not reviewer:
            raise Rejected('denied')
        if not source.responsible_operator_id:
            raise Rejected('unavailable')
        instant(source.received_at)
        return actor, source, reviewer

    async def read(self, credential, subject, organization, operation=None):
        actor, source, reviewer = await self.authority(credential, subject, organization)
        with self.connect() as db:
            row = db.execute('SELECT body FROM l18_dispute_cases WHERE subject=?', (subject,)).fetchone()
            if not row:
                raise Rejected('denied')
            case = json.loads(row['body'])
            if operation:
                row = db.execute('SELECT * FROM l18_dispute_operations WHERE operation=? AND subject=?', (operation, subject)).fetchone()
                if not row or (row['actor'] != actor and not (reviewer and row['binding'])):
                    raise Rejected('denied')
        if operation:
            await self.deliver(operation)
            await self.authority(credential, subject, organization)
            with self.connect() as db:
                case = json.loads(db.execute('SELECT body FROM l18_dispute_operations WHERE operation=?', (operation,)).fetchone()['body'])
        return self.public(case)

    async def context(self, credential, subject, organization):
        actor, source, reviewer = await self.authority(credential, subject, organization)
        with self.connect() as db:
            row = db.execute('SELECT body FROM l18_dispute_cases WHERE subject=?', (subject,)).fetchone()
        case = json.loads(row['body']) if row else None
        return {'source_revision': source.revision, 'assignment_revision': source.assignment_revision,
                'expected_revision': case['revision'] if case else 0,
                'principal_minor': source.principal_minor,
                'closing_at': (source.received_at + timedelta(hours=72 if source.kind == 'private_watch' else 168)).isoformat(),
                'actions': ([] if case and case['state'] not in ('open', 'responded') else ['refund', 'release'] if reviewer and case else ['respond'] if actor in (source.seller_id, *source.business_responders) and case else ['open'] if not case and not reviewer else []),
                'case': case}

    @staticmethod
    def public(case):
        return {k: v for k, v in case.items() if k not in ('reason', 'evidence', 'response', 'decision', 'hold_operation_id')}

    async def command(self, credential, command: Command):
        actor, source, reviewer = await self.authority(credential, command.subject_id, command.organization_id)
        request = command.model_dump(mode='json')
        request_hash = digest(request)
        with self.connect() as db:
            prior = db.execute('SELECT * FROM l18_dispute_operations WHERE operation=?', (command.operation_id,)).fetchone()
            if prior:
                if prior['actor'] != actor or prior['request_hash'] != request_hash:
                    raise Rejected('conflict')
        if prior:
            return await self.read(credential, source.subject_id, source.organization_id, command.operation_id)
        if source.revision != command.source_revision or source.assignment_revision != command.assignment_revision:
            raise Rejected('stale')
        evidence = [e.model_dump() for e in command.evidence]
        if sum(e['size'] for e in evidence) > 15_000_000 or len({e['reference'] for e in evidence}) != len(evidence):
            raise Rejected('evidence')
        if evidence and await self.bounded(self.providers.evidence(credential, source.subject_id, evidence)) is not True:
            raise Rejected('evidence')
        current_actor, source, reviewer = await self.authority(credential, command.subject_id, command.organization_id)
        if current_actor != actor:
            raise Rejected('denied')
        if source.revision != command.source_revision or source.assignment_revision != command.assignment_revision:
            raise Rejected('stale')
        now = instant(self.clock())
        closing = source.received_at + timedelta(hours=72 if source.kind == 'private_watch' else 168)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Recheck after acquiring the write lock for concurrent identical retries.
            prior = db.execute('SELECT * FROM l18_dispute_operations WHERE operation=?', (command.operation_id,)).fetchone()
            if prior:
                if prior['actor'] != actor or prior['request_hash'] != request_hash:
                    raise Rejected('conflict')
                return self.public(json.loads(prior['body']))
            row = db.execute('SELECT body FROM l18_dispute_cases WHERE subject=?', (source.subject_id,)).fetchone()
            case = json.loads(row['body']) if row else None
            if command.kind == 'open' and case:
                return self.public(case)
            if command.expected_revision != (case['revision'] if case else 0):
                raise Rejected('stale')
            if command.kind == 'open':
                if actor not in (source.buyer_id, source.seller_id, *source.business_responders) or command.amount_minor:
                    raise Rejected('denied')
                if now < source.received_at or not source.ready:
                    raise Rejected('prerequisites')
                if now >= closing:
                    raise Rejected('late', closing.isoformat())
                case = {'schema_version': 'disputes.v1', 'subject_id': source.subject_id,
                        'watch_id': source.watch_id, 'currency': 'USD', 'revision': 0,
                        'reason': command.reason, 'evidence': evidence, 'closing_at': closing.isoformat()}
            elif not case:
                raise Rejected('prerequisites')
            elif case['state'] not in ('open', 'responded'):
                raise Rejected('pending')
            if command.kind == 'respond':
                if actor not in (source.seller_id, *source.business_responders) or command.amount_minor:
                    raise Rejected('denied')
                case['response'] = {'reason': command.reason, 'evidence': evidence, 'actor': actor}
            if command.kind in ('refund', 'release'):
                if not reviewer:
                    raise Rejected('denied')
                if command.kind == 'refund' and not 0 < command.amount_minor <= source.principal_minor:
                    raise Rejected('invalid')
                if command.kind == 'release' and command.amount_minor:
                    raise Rejected('invalid')
                case['decision'] = {'reason': command.reason, 'actor': actor, 'assignment_revision': source.assignment_revision, 'evidence': evidence}
            financial = command.kind != 'respond'
            case.update(operation_id=command.operation_id, actor_id=actor,
                        organization_id=source.organization_id, expected_revision=command.expected_revision,
                        state={'open': 'hold_pending', 'respond': 'responded', 'refund': 'refund_pending', 'release': 'release_pending'}[command.kind],
                        revision=case['revision'] + 1, pending_reason='orders_confirmation' if financial else None,
                        next_actor=source.responsible_operator_id, next_action='confirm_orders' if financial else 'independent_review', next_review_at=(now + timedelta(hours=24)).isoformat(),
                        financial_operation_id='dispute_' + command.operation_id if financial else None,
                        amount_minor=command.amount_minor)
            binding = None
            if financial:
                binding = {**source.__dict__, 'received_at': source.received_at.isoformat(),
                           'actor_id': actor, 'operation_id': command.operation_id,
                           'financial_operation_id': case['financial_operation_id'], 'kind': command.kind,
                           'closing_at': closing.isoformat(), 'amount_minor': command.amount_minor,
                           'request_hash': request_hash, 'hold_operation_id': case.get('hold_operation_id')}
                binding['binding_hash'] = digest(binding)
            if command.kind == 'open':
                case['hold_operation_id'] = case['financial_operation_id']
            encoded = json.dumps(case)
            db.execute('INSERT OR REPLACE INTO l18_dispute_cases VALUES(?,?,?)', (source.subject_id, case['revision'], encoded))
            db.execute('INSERT INTO l18_dispute_operations VALUES(?,?,?,?,?,?)',
                       (command.operation_id, source.subject_id, actor, request_hash, json.dumps(binding) if binding else None, encoded))
        return await self.read(credential, source.subject_id, source.organization_id, command.operation_id)

    async def deliver(self, operation):
        with self.connect() as db:
            row = db.execute('SELECT * FROM l18_dispute_operations WHERE operation=?', (operation,)).fetchone()
        case = json.loads(row['body'])
        if not row['binding'] or not case['state'].endswith('_pending'):
            return
        binding = json.loads(row['binding'])
        try:
            receipt = await self.bounded(self.providers.apply(binding))
        except Rejected:
            return
        if not isinstance(receipt, dict):
            return
        if receipt.get('binding_hash') != binding['binding_hash'] or receipt.get('state') not in ('confirmed', 'denied'):
            return
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = json.loads(db.execute('SELECT body FROM l18_dispute_operations WHERE operation=?', (operation,)).fetchone()['body'])
            if not latest['state'].endswith('_pending'):
                return
            denied = receipt['state'] == 'denied'
            latest['state'] = ('denied' if binding['kind'] == 'open' else 'open') if denied else {'open': 'open', 'refund': 'refunded', 'release': 'released'}[binding['kind']]
            latest['pending_reason'] = 'orders_denied' if denied else None
            latest['next_action'] = 'support_review' if denied else 'independent_review' if binding['kind'] == 'open' else 'closed'
            latest['revision'] += 1
            db.execute('UPDATE l18_dispute_operations SET body=? WHERE operation=?', (json.dumps(latest), operation))
            db.execute('UPDATE l18_dispute_cases SET body=?,revision=? WHERE subject=?', (json.dumps(latest), latest['revision'], latest['subject_id']))
