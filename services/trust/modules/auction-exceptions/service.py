"""Durable private receipts; allocation and competition remain producer-owned."""
import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Denied(Exception):
    pass


class Provider(Protocol):
    async def authorize(self, command, principal):
        """Recheck current scope and return responsible operator or raise Denied."""
    async def execute(self, command):
        """Idempotent canonical action, including coordinated order exception after close."""


class Service:
    def __init__(self, database, provider: Provider, clock=None):
        descriptor = os.open(database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.database = database
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts (operation TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.database, timeout=1)

    async def authorized(self, command, principal):
        if principal.get('actor_id') != command.actor_id or principal.get('organization_id') != command.organization_id:
            raise Denied('permission_denied')
        owner = await asyncio.wait_for(self.provider.authorize(command.payload(), principal), 1.2)
        if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
            raise Denied('permission_denied')
        return owner

    async def lookup(self, command, principal):
        await self.authorized(command, principal)
        with self.connect() as db:
            row = db.execute('SELECT payload,result FROM receipts WHERE operation=?', (command.operation_id,)).fetchone()
        if row is None:
            return None
        if row[0] != json.dumps(command.payload(), sort_keys=True):
            raise Denied('operation_conflict')
        return json.loads(row[1])

    async def submit(self, command, principal):
        owner = await self.authorized(command, principal)
        now = self.clock()
        if now.utcoffset() != timedelta(0):
            raise ValueError('utc_required')
        pending = {key: value for key, value in command.payload().items() if key in (
            'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision', 'quote_id', 'quote_revision', 'policy_revision', 'assignment_revision')}
        pending.update(schema_version='auction-exceptions.v1', state='pending', revision=command.expected_revision,
                       pending_reason='lookup_required', code='lookup_required', next_actor=owner,
                       next_review_at=(now + timedelta(hours=24)).isoformat(),
                       next_action='lookup_and_coordinate', escalation_at=(now + timedelta(hours=48)).isoformat())
        payload = json.dumps(command.payload(), sort_keys=True)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO receipts VALUES (?,?,?)', (command.operation_id, payload, json.dumps(pending)))
            row = db.execute('SELECT payload,result FROM receipts WHERE operation=?', (command.operation_id,)).fetchone()
        if row[0] != payload:
            raise Denied('operation_conflict')
        saved = json.loads(row[1])
        if saved['state'] != 'pending':
            return saved
        try:
            receipt = await asyncio.wait_for(self.provider.execute(command.payload()), 1.2)
            # Accept only a bound canonical receipt; discard all extra/private fields.
            if any(receipt.get(key) != value for key, value in pending.items()
                   if key in ('schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision', 'quote_id', 'quote_revision', 'policy_revision', 'assignment_revision')):
                return saved
            if receipt.get('state') not in ('acknowledged', 'denied', 'pending'):
                return saved
            if type(receipt.get('revision')) is not int or not 0 <= receipt['revision'] <= 2**53 - 1:
                return saved
            if receipt['revision'] < command.expected_revision and (receipt['state'], receipt.get('code')) != ('denied', 'stale_revision'):
                return saved
            if receipt.get('code') not in ('competition_recomputed', 'auction_cancelled', 'seller_ended',
                    'order_exception_recorded', 'order_exception_resolved', 'bids_present', 'permission_denied', 'stale_revision', 'lookup_required'):
                return saved
            result = dict(saved, next_actor=owner, state=receipt['state'], revision=receipt['revision'], code=receipt['code'])
            if result['state'] != 'pending':
                result.update(pending_reason=None, next_actor=None, next_review_at=None, next_action=None, escalation_at=None)
            with self.connect() as db:
                # A concurrent uncertain retry cannot overwrite a terminal receipt.
                db.execute('BEGIN IMMEDIATE')
                current = json.loads(db.execute('SELECT result FROM receipts WHERE operation=?', (command.operation_id,)).fetchone()[0])
                if current['state'] != 'pending':
                    return current
                db.execute('UPDATE receipts SET result=? WHERE operation=?', (json.dumps(result), command.operation_id))
            return result
        except (TimeoutError, ConnectionError, OSError, ValueError, TypeError, KeyError):
            return saved
