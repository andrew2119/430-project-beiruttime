"""Private, durable challenge admission with bounded identity completion."""
import asyncio
import hashlib
import hmac
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


class Denied(Exception):
    """No identity or credential details are included in public failures."""


class Stale(Denied):
    pass


@dataclass(frozen=True)
class Scope:
    browser: str
    actor_id: str | None = None
    organization_id: str | None = None
    revision: int = 0


@dataclass(frozen=True)
class Claims:
    issuer: str
    audience: str
    subject: str
    recipient: str
    recipient_verified: bool
    nonce: str
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class Binding:
    operation_id: str
    browser_hash: str
    actor_id: str | None
    organization_id: str | None
    expected_revision: int
    issuer: str
    external_subject: str
    recipient: str
    proof_hash: str
    verified_at: int


@dataclass(frozen=True)
class Receipt:
    subject_id: str
    state: str
    revision: int


class Provider(Protocol):
    async def exchange(self, code: str) -> Claims:
        """Validate configured signature/algorithm before returning claims."""
        ...


class Identity(Protocol):
    async def complete(self, binding: Binding, proof: str) -> Receipt:
        """Atomically recheck authority, consume exact proof and retain receipt."""
        ...

    async def current(self, binding: Binding) -> Receipt:
        """Recheck current scope and original session, never mint a new session."""
        ...


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def same(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


class Store:
    """Local durable adapter; deployment supplies a service-private database."""
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=1, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript((Path(__file__).parent / 'migrations' /
                               'L22_0001_external_sign_in.sql').read_text())

    def close(self):
        self.db.close()

    def row(self, operation_id):
        return self.db.execute('SELECT * FROM l22_external_operations WHERE operation_id=?', (operation_id,)).fetchone()


class Service:
    def __init__(self, store: Store, provider: Provider, identity: Identity, *, issuer: str,
                 audience: str, clock, deadline: float = 2):
        self.store, self.provider, self.identity = store, provider, identity
        self.issuer, self.audience, self.clock, self.deadline = issuer, audience, clock, deadline

    def _scope(self, row, scope):
        if (not row or len(scope.browser) < 32 or
                not same(row['browser_hash'], digest(scope.browser)) or
                row['actor_id'] != scope.actor_id or row['organization_id'] != scope.organization_id):
            raise Denied()
        if row['expected_revision'] != scope.revision:
            raise Stale()

    def begin(self, operation_id: str, scope: Scope):
        if (not 16 <= len(operation_id) <= 100 or
                any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in operation_id) or
                not 32 <= len(scope.browser) <= 128 or scope.revision < 0 or
                (scope.organization_id is not None and scope.actor_id is None)):
            raise Denied()
        now = self.clock()
        # The random private browser binding is the recovery key; only hashes persist.
        def token(label):
            return hmac.new(scope.browser.encode(),
                            f'{label}:{operation_id}'.encode(), hashlib.sha256).hexdigest()
        state, nonce = token('state'), token('nonce')
        db = self.store.db
        db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.store.row(operation_id)
            if prior:
                self._scope(prior, scope)
                db.execute('COMMIT')
                if prior['state'] != 'ready' or now >= prior['expires_at']:
                    return self._result(prior, 'denied' if prior['state'] == 'ready' else
                                        'pending' if prior['state'] in ('signed_in', 'linked') else None)
                return {'schema_version': 1, 'operation_id': operation_id, 'state': state,
                        'nonce': nonce, 'expires_at': prior['expires_at'], 'return_path': '/account'}
            if db.execute('SELECT count(*) FROM l22_external_operations WHERE browser_hash=? AND created_at>?',
                          (digest(scope.browser), now - 3600)).fetchone()[0] >= 5:
                raise Denied()
            db.execute('''INSERT INTO l22_external_operations
                (operation_id,browser_hash,actor_id,organization_id,expected_revision,
                 state_hash,nonce_hash,issuer,audience,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                       (operation_id, digest(scope.browser), scope.actor_id, scope.organization_id,
                        scope.revision, digest(state), digest(nonce), self.issuer, self.audience, now, now + 600))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise Denied() from None
        return {'schema_version': 1, 'operation_id': operation_id, 'state': state,
                'nonce': nonce, 'expires_at': now + 600, 'return_path': '/account'}

    def _result(self, row, state=None):
        state = state or row['state']
        return dict(schema_version=1, operation_id=row['operation_id'],
                    subject_id=row['subject_id'] if state in ('signed_in', 'linked') else None,
                    watch_id=None, actor_id=row['actor_id'], organization_id=row['organization_id'],
                    expected_revision=row['expected_revision'], state=state, revision=row['revision'],
                    pending_reason='identity_unavailable' if state == 'pending' else None,
                    next_actor='identity' if state == 'pending' else 'buyer', next_review_at=None)

    async def callback(self, command, scope: Scope, proof: str = ''):
        row = self.store.row(command.operation_id)
        self._scope(row, scope)
        if command.expected_revision != row['expected_revision']:
            return self._result(row, 'stale')
        if not same(row['state_hash'], digest(command.state)):
            self._failed(row)
            raise Denied()
        request_hash = digest(json.dumps([command.model_dump(), digest(proof)], sort_keys=True))
        if row['request_hash'] and not same(row['request_hash'], request_hash):
            raise Denied()
        if row['state'] in ('signed_in', 'linked'):
            return await self.lookup(command.operation_id, scope)
        if row['state'] in ('denied', 'stale'):
            return self._result(row)
        if row['binding'] is None:
            if self.clock() >= row['expires_at'] or row['attempts'] >= 5:
                self._terminal(row, 'denied')
                return self._result(self.store.row(command.operation_id))
            try:
                claims = await asyncio.wait_for(self.provider.exchange(command.code), self.deadline)
                now = self.clock()
                if not isinstance(claims, Claims) or not all(type(value) is str for value in (
                        claims.issuer, claims.audience, claims.subject, claims.recipient, claims.nonce)):
                    raise Denied()
                if (claims.issuer != row['issuer'] or claims.audience != row['audience'] or
                        claims.recipient_verified is not True or
                        not 1 <= len(claims.subject) <= 255 or not 3 <= len(claims.recipient) <= 254 or
                        claims.recipient.count('@') != 1 or any(c.isspace() for c in claims.recipient) or
                        not same(digest(claims.nonce), row['nonce_hash']) or
                        type(claims.issued_at) is not int or type(claims.expires_at) is not int or
                        claims.issued_at > now or claims.expires_at <= now or
                        now >= row['expires_at']):
                    raise Denied()
            except (TimeoutError, ConnectionError):
                return self._result(row, 'unavailable')
            except Denied:
                self._failed(row)
                raise Denied() from None
            except Exception:
                return self._result(row, 'unavailable')
            binding = Binding(command.operation_id, row['browser_hash'], scope.actor_id,
                              scope.organization_id, scope.revision, claims.issuer, claims.subject,
                              claims.recipient, digest(proof), now)
            # Compare-and-set consumes the challenge once even with concurrent callbacks.
            changed = self.store.db.execute('''UPDATE l22_external_operations
                SET binding=?,request_hash=?,state='pending',revision=revision+1
                WHERE operation_id=? AND binding IS NULL AND state='ready' AND attempts<5''',
                (json.dumps(asdict(binding), sort_keys=True), request_hash, command.operation_id)).rowcount
            row = self.store.row(command.operation_id)
            if not changed and row['request_hash'] != request_hash:
                raise Denied()
        binding = Binding(**json.loads(row['binding']))
        try:
            receipt = await asyncio.wait_for(self.identity.complete(binding, proof), self.deadline)
            self._receipt(binding, receipt)
        except (TimeoutError, ConnectionError):
            return self._result(row, 'pending')
        except Stale:
            self._terminal(row, 'stale')
        except Denied:
            self._terminal(row, 'denied')
        except Exception:
            return self._result(row, 'pending')
        return self._result(self.store.row(command.operation_id))

    def _failed(self, row):
        self.store.db.execute('''UPDATE l22_external_operations SET attempts=attempts+1,
            state=CASE WHEN attempts>=4 THEN 'denied' ELSE state END,
            revision=revision+1 WHERE operation_id=? AND binding IS NULL''', (row['operation_id'],))

    def _terminal(self, row, state):
        self.store.db.execute('''UPDATE l22_external_operations SET state=?,revision=revision+1,
            subject_id=NULL WHERE operation_id=?''', (state, row['operation_id']))

    def _receipt(self, binding, receipt):
        if (not isinstance(receipt, Receipt) or type(receipt.revision) is not int or
                receipt.state != ('linked' if binding.actor_id else 'signed_in') or
                not receipt.subject_id or receipt.revision < binding.expected_revision or
                (binding.actor_id and receipt.subject_id != binding.actor_id)):
            raise Denied()
        self.store.db.execute('''UPDATE l22_external_operations SET state=?,subject_id=?,
            revision=revision+1 WHERE operation_id=? AND state='pending' ''',
            (receipt.state, receipt.subject_id, binding.operation_id))

    async def lookup(self, operation_id: str, scope: Scope):
        row = self.store.row(operation_id)
        self._scope(row, scope)
        if row['state'] == 'ready' and self.clock() >= row['expires_at']:
            self._terminal(row, 'denied')
            return self._result(self.store.row(operation_id))
        if row['state'] in ('signed_in', 'linked', 'pending'):
            try:
                binding = Binding(**json.loads(row['binding']))
                receipt = await asyncio.wait_for(self.identity.current(binding), self.deadline)
                self._receipt(binding, receipt)
            except (TimeoutError, ConnectionError):
                return self._result(row, 'pending')
            except Stale:
                self._terminal(row, 'stale')
            except Denied:
                self._terminal(row, 'denied')
            except Exception:
                return self._result(row, 'pending')
        return self._result(self.store.row(operation_id))
