"""Durable optional delivery. Inbox remains the only notice authority."""
import asyncio
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


class Denied(Exception):
    code = 'denied'


class Conflict(Exception):
    code = 'stale_revision'


class Pending(Exception):
    code = 'unavailable'


@dataclass(frozen=True)
class Identity:
    actor: str
    session: str
    access_revision: int
    organization: str | None = None


class Store:
    """Module-local durable adapter; use a private persistent file, never a cache."""
    _locks = {}

    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript((Path(__file__).parent / 'migrations/L20_0001_browser_push.sql').read_text())
        self.lock = self._locks.setdefault(str(Path(path).resolve()), asyncio.Lock())

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self.db
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def close(self):
        self.db.close()


class BrowserPush:
    def __init__(self, store, current_identity, inbox, delivery, allowed_endpoint, protect, reveal):
        self.store, self.current_identity, self.inbox = store, current_identity, inbox
        self.delivery, self.allowed_endpoint = delivery, allowed_endpoint
        self.protect, self.reveal = protect, reveal

    async def bounded(self, call):
        try:
            return await asyncio.wait_for(call, timeout=3)
        except (TimeoutError, OSError):
            raise Pending() from None

    async def identity(self, credential):
        identity = await self.bounded(self.current_identity(credential))
        if not identity or identity.organization is not None:
            raise Denied()
        return identity

    async def current_notice(self, identity, notice_id):
        value = await self.bounded(self.inbox(identity, notice_id))
        if value is None:
            return None
        try:
            if value['schema_version'] != 'browser-push.inbox.v1' or type(value['available']) is not bool:
                raise ValueError()
            if not isinstance(value['recipient_id'], str) or not isinstance(value['kind'], str):
                raise ValueError()
            expires = datetime.fromisoformat(value['expires_at'])
            if expires.tzinfo is None or expires.utcoffset() != timezone.utc.utcoffset(expires):
                raise ValueError()
            return {'recipient_id': value['recipient_id'], 'available': value['available'],
                    'kind': value['kind'], 'expires_at': expires}
        except (KeyError, TypeError, ValueError):
            raise Pending() from None

    @staticmethod
    def capability(value):
        if not isinstance(value, str) or not 32 <= len(value) <= 256:
            raise Denied()
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def owns(row, identity, capability):
        return (row and row['capability'] == capability and row['actor'] == identity.actor
                and row['session'] == identity.session and row['access_revision'] == identity.access_revision)

    async def command(self, credential, capability, body):
        identity = await self.identity(credential)
        cap = self.capability(capability)
        request = body.model_dump(mode='json')
        fingerprint = hashlib.sha256(json.dumps([request, identity.actor, identity.session, identity.access_revision], sort_keys=True).encode()).hexdigest()
        device, operation = str(body.device_id), str(body.operation_id)
        if body.action != 'revoke':
            if body.permission != 'granted' or body.subscription is None:
                raise Denied()
            if not self.allowed_endpoint(body.subscription.endpoint):
                raise Denied()
        async with self.store.lock:
            with self.store.transaction() as db:
                if db.execute('SELECT 1 FROM l20_push_revoked_sessions WHERE actor=? AND session=?', (identity.actor, identity.session)).fetchone():
                    raise Denied()
                old = db.execute('SELECT * FROM l20_push_devices WHERE id=?', (device,)).fetchone()
                prior = db.execute('SELECT * FROM l20_push_receipts WHERE operation=?', (operation,)).fetchone()
                if prior:
                    if (prior['actor'], prior['session']) != (identity.actor, identity.session):
                        raise Denied()
                    if prior['fingerprint'] != fingerprint or not self.owns(old, identity, cap):
                        raise Conflict()
                    return json.loads(prior['result'])
                if old and old['capability'] != cap:
                    raise Denied()
                if old and not self.owns(old, identity, cap) and body.action != 'rebind':
                    raise Denied()
                revision = old['revision'] if old else 0
                if revision != body.expected_revision:
                    raise Conflict()
                if body.action == 'opt_in' and old and old['active']:
                    raise Conflict()
                active = body.action != 'revoke'
                revision += 1
                subscription = self.protect(body.subscription.model_dump_json()) if active else None
                db.execute('''INSERT INTO l20_push_devices VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET actor=excluded.actor,session=excluded.session,
                    access_revision=excluded.access_revision,revision=excluded.revision,
                    active=excluded.active,subscription=excluded.subscription''',
                    (device, cap, identity.actor, identity.session, identity.access_revision, revision, int(active), subscription))
                result = dict(schema_version='browser-push.v1', operation_id=operation, device_id=device,
                              state='active' if active else 'revoked', revision=revision)
                db.execute('INSERT INTO l20_push_receipts VALUES(?,?,?,?,?)',
                           (operation, identity.actor, identity.session, fingerprint, json.dumps(result)))
                return result

    async def lookup(self, credential, operation):
        identity = await self.identity(credential)
        row = self.store.db.execute('SELECT * FROM l20_push_receipts WHERE operation=?', (str(operation),)).fetchone()
        if not row or (row['actor'], row['session']) != (identity.actor, identity.session):
            raise Denied()
        return json.loads(row['result'])

    async def device(self, credential, capability, device):
        identity = await self.identity(credential)
        row = self.store.db.execute('SELECT * FROM l20_push_devices WHERE id=?', (str(device),)).fetchone()
        if not row:
            return dict(state='unbound', revision=0)
        if row['capability'] != self.capability(capability):
            raise Denied()
        # The capability holder may see the revision needed for an explicit rebind,
        # but no old identity or subscription is exposed.
        return dict(state='active' if self.owns(row, identity, row['capability']) and row['active'] else 'revoked', revision=row['revision'])

    async def revoke_session(self, actor, session):
        """Host calls before acknowledging logout or accepting identity change."""
        async with self.store.lock:
            with self.store.transaction() as db:
                db.execute('INSERT OR IGNORE INTO l20_push_revoked_sessions VALUES(?,?)', (actor, session))
                db.execute('''UPDATE l20_push_devices SET active=0,subscription=NULL,revision=revision+1
                              WHERE actor=? AND session=? AND active=1''', (actor, session))

    async def dispatch(self, credential, notice_id, device_id, now):
        """One worker adapter; stable delivery key, maximum three attempts."""
        UUID(notice_id)
        UUID(device_id)
        if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
            raise ValueError('UTC required')
        identity = await self.identity(credential)
        # Serialize delivery with revocation. The delivery port must honor its
        # idempotency key even when the transport response is lost.
        async with self.store.lock:
            with self.store.transaction() as db:
                if db.execute('SELECT 1 FROM l20_push_revoked_sessions WHERE actor=? AND session=?', (identity.actor, identity.session)).fetchone():
                    raise Denied()
                row = db.execute('SELECT * FROM l20_push_devices WHERE id=?', (device_id,)).fetchone()
                if not row or not row['active'] or (row['actor'], row['session'], row['access_revision']) != (identity.actor, identity.session, identity.access_revision):
                    raise Denied()
                notice = await self.current_notice(identity, notice_id)
                if not notice or notice['kind'] not in {'outbid', 'win', 'message', 'action_needed'}:
                    raise Denied()
                if not notice['available'] or notice['recipient_id'] != identity.actor:
                    raise Denied()
                expires = notice['expires_at']
                if expires.tzinfo is None or now >= expires:
                    return 'expired'
                key = (notice_id, device_id, row['revision'])
                prior = db.execute('SELECT * FROM l20_push_deliveries WHERE notice=? AND device=? AND revision=?', key).fetchone()
                if prior and (prior['state'] == 'sent' or prior['attempts'] >= 3):
                    return prior['state']
                attempts = prior['attempts'] + 1 if prior else 1
                db.execute('INSERT OR REPLACE INTO l20_push_deliveries VALUES(?,?,?,?,?)', (*key, attempts, 'pending'))
            payload = {'schema_version': 'browser-push.v1', 'kind': 'notice'}
            delivery_key = hashlib.sha256(':'.join(map(str, key)).encode()).hexdigest()
            try:
                status = await self.bounded(self.delivery(json.loads(self.reveal(row['subscription'])), payload, delivery_key))
            except Pending:
                status = 'pending'
            with self.store.transaction() as db:
                if status in {'gone', 'denied'}:
                    db.execute('UPDATE l20_push_devices SET active=0,subscription=NULL,revision=revision+1 WHERE id=? AND revision=? AND actor=? AND session=?', (device_id, row['revision'], identity.actor, identity.session))
                state = 'sent' if status == 'sent' else 'pending' if status == 'pending' else 'failed'
                db.execute('UPDATE l20_push_deliveries SET state=? WHERE notice=? AND device=? AND revision=?', (state, *key))
            return state

    async def destination(self, credential, notice_id):
        identity = await self.identity(credential)
        notice = await self.current_notice(identity, str(notice_id))
        if not notice or not notice['available'] or notice['recipient_id'] != identity.actor:
            raise Denied()
        return {'url': '/inbox'}
