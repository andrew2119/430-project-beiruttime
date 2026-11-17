"""Durable private factor state with current-authority admission."""
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Rejected(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Authority:
    allowed: bool = False
    session_id: str = ''
    password_fresh: bool = False
    controllers: tuple[str, ...] = ()
    recovery_case: str = ''
    identity_producer: bool = False
    protected_producer: bool = False


def totp(secret: str, step: int) -> str:
    key = base64.b32decode(secret)
    value = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = value[-1] & 15
    return f'{(int.from_bytes(value[offset:offset + 4], "big") & 0x7fffffff) % 1000000:06d}'


def digits(value):
    return value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))


def authorize(command, authority):
    if not isinstance(authority, Authority) or not authority.allowed or not authority.session_id:
        raise Rejected('denied')
    if command.kind != 'revoke_ack' and command.actor_id != command.subject_id:
        raise Rejected('denied')
    if command.kind == 'revoke_ack' and not authority.identity_producer:
        raise Rejected('denied')
    if command.kind == 'consume' and not authority.protected_producer:
        raise Rejected('denied')
    return authority


class FactorEngine:
    def __init__(self, key):
        if len(key) != 32:
            raise ValueError('key_length')
        self.key = key

    def seal(self, subject, value):
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(self.key).encrypt(nonce, json.dumps(value).encode(), subject.encode())

    def open(self, subject, value):
        return json.loads(AESGCM(self.key).decrypt(value[:12], value[12:], subject.encode()))

    def digest(self, value):
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def receipt(self, state, authority, result, command):
        return {'session_id': authority.session_id, 'generation': state.get('generation'),
                'binding': self.lookup_binding(command), 'result': result}

    def lookup_binding(self, command):
        return self.digest(json.dumps(command.model_dump(exclude={'proof'}), sort_keys=True))

    def read_receipt(self, command, sealed, state, authority):
        receipt = self.open(command.subject_id, sealed)
        result = receipt['result']
        private = command.kind == 'consume' or any(key in result for key in ('secret', 'recovery_codes', 'proof_id'))
        if (receipt['binding'] != self.lookup_binding(command)
                or receipt['generation'] != state.get('generation')
                or authority.session_id == state.get('blocked_session')
                or (private and receipt['session_id'] != authority.session_id)):
            raise Rejected('denied')
        if result['state'] == 'pending' and state['status'] == 'empty':
            return dict(result, state='sign_in_required', revision=state['revision'],
                        pending_reason=None, next_actor=None, next_review_at=None)
        return result

    def apply(self, c, a, s, now):
        if c.kind == 'revoke_ack':
            if not a.identity_producer or s['status'] != 'pending' or c.proof_id != s['revocation_id']:
                raise Rejected('denied')
            s.update(status='empty', blocked_session=s['old_session'])
            return {'state': 'sign_in_required'}
        if s['status'] == 'pending':
            raise Rejected('unavailable')
        if a.session_id == s.get('blocked_session'):
            raise Rejected('denied')
        if c.kind == 'recover':
            if (not a.password_fresh or len(set(a.controllers)) != 2 or len(a.controllers) != 2
                    or c.subject_id in a.controllers or not a.recovery_case or a.recovery_case != c.record_id):
                raise Rejected('denied')
            revision = s['revision']
            s.clear()
            s.update(revision=revision, generation=c.operation_id, status='pending', proofs={}, old_session=a.session_id,
                     revocation_id=c.operation_id)
            return {'state': 'pending'}
        if c.kind == 'enroll':
            if not a.password_fresh or s['status'] == 'enabled':
                raise Rejected('denied')
            if s['status'] == 'enrolling' and now < s['enrollment_expires']:
                raise Rejected('conflict')
            secret = base64.b32encode(secrets.token_bytes(20)).decode()
            s.update(status='enrolling', generation=c.operation_id, secret=secret, enrollment_expires=now + 600,
                     last_step=-1, codes=[], proofs={})
            return {'state': 'enrolling', 'secret': secret, 'expires_at': self.instant(now + 600)}
        if c.kind == 'confirm':
            if s['status'] != 'enrolling' or now >= s['enrollment_expires']:
                raise Rejected('expired')
            self.verify(s, c.proof, now, recovery=False)
            codes = [secrets.token_hex(16) for _ in range(10)]
            s.update(status='enabled', codes=[self.digest(code) for code in codes])
            return {'state': 'enabled', 'recovery_codes': codes}
        if s['status'] != 'enabled':
            raise Rejected('denied')
        if not c.action or not c.record_id or c.record_revision is None:
            raise Rejected('denied')
        binding = [c.actor_id, a.session_id, c.organization_id, c.action, c.record_id, c.record_revision]
        if c.action == 'business_payout' and not c.organization_id:
            raise Rejected('denied')
        if c.kind == 'prove':
            self.verify(s, c.proof, now)
            proof_id = secrets.token_urlsafe(24)
            s['proofs'] = {k: v for k, v in s['proofs'].items() if v['expires'] > now}
            if len(s['proofs']) >= 10:
                raise Rejected('try_later')
            s['proofs'][proof_id] = {'binding': binding, 'expires': now + 300}
            return {'state': 'proved', 'proof_id': proof_id, 'expires_at': self.instant(now + 300)}
        if c.kind == 'consume':
            proof = s['proofs'].get(c.proof_id)
            if not a.protected_producer or not proof or proof['binding'] != binding:
                raise Rejected('denied')
            if now >= proof['expires']:
                raise Rejected('expired')
            del s['proofs'][c.proof_id]
            return {'state': 'consumed'}
        raise Rejected('denied')

    def verify(self, state, supplied, now, recovery=True):
        supplied = digits(supplied or '')
        if len(supplied) == 6 and supplied.isascii() and supplied.isdigit():
            step = now // 30
            for candidate in (step, step - 1, step + 1):
                if candidate >= 0 and candidate > state['last_step'] and hmac.compare_digest(
                        totp(state['secret'], candidate), supplied):
                    state['last_step'] = candidate
                    return
        if recovery:
            digest = self.digest(supplied)
            for code in state['codes']:
                if hmac.compare_digest(code, digest):
                    state['codes'].remove(code)
                    return
        raise Rejected('invalid_proof')

    @staticmethod
    def instant(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


class FactorStore(FactorEngine):
    """Single-service durable fixture; external authority is never cached."""
    def __init__(self, path: str, key: bytes, authority: Callable, clock: Callable):
        super().__init__(key)
        self.authority, self.clock = authority, clock
        self.db = sqlite3.connect(path, timeout=2, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS factors(subject TEXT PRIMARY KEY, data BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(subject TEXT, operation TEXT, digest TEXT, result BLOB,
                PRIMARY KEY(subject,operation));
            CREATE TABLE IF NOT EXISTS attempts(subject TEXT PRIMARY KEY, window INTEGER, count INTEGER);
        ''')

    def close(self):
        self.db.close()

    def admit(self, command):
        try:
            authority = self.authority(command)
        except Exception:
            raise Rejected('unavailable') from None
        return authorize(command, authority)

    def lookup(self, command):
        authority = self.admit(command)
        row = self.db.execute('''SELECT o.result,f.data FROM operations o JOIN factors f
            ON o.subject=f.subject WHERE o.subject=? AND o.operation=?''',
                              (command.subject_id, command.operation_id)).fetchone()
        if not row:
            raise Rejected('unavailable')
        state = self.open(command.subject_id, row[1])
        return self.read_receipt(command, row[0], state, authority)

    def committed(self, command, authority):
        row = self.db.execute('''SELECT o.digest,o.result,f.data FROM operations o JOIN factors f
            ON o.subject=f.subject WHERE o.subject=? AND o.operation=?''',
                              (command.subject_id, command.operation_id)).fetchone()
        if row is None:
            return None
        if not hmac.compare_digest(row[0], self.digest(command.model_dump_json())):
            raise Rejected('conflict')
        return self.read_receipt(command, row[1], self.open(command.subject_id, row[2]), authority)

    def execute(self, command):
        authority = self.admit(command)
        prior = self.committed(command, authority)
        if prior is not None:
            return prior
        now = int(self.clock())
        subject = command.subject_id
        payload = self.digest(command.model_dump_json())
        # Failed proofs consume a durable budget even when the state transaction rolls back.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT window,count FROM attempts WHERE subject=?', (subject,)).fetchone()
            window, count = row if row and now < row[0] + 300 else (now, 0)
            if count >= 10:
                raise Rejected('try_later')
            self.db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (subject, window, count + 1))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        self.db.execute('BEGIN IMMEDIATE')
        try:
            authority = self.admit(command)
            now = int(self.clock())
            prior = self.db.execute('SELECT digest,result FROM operations WHERE subject=? AND operation=?',
                                    (subject, command.operation_id)).fetchone()
            row = self.db.execute('SELECT data FROM factors WHERE subject=?', (subject,)).fetchone()
            state = self.open(subject, row[0]) if row else {'revision': 0, 'status': 'empty', 'proofs': {}}
            if prior:
                if not hmac.compare_digest(prior[0], payload):
                    raise Rejected('conflict')
                result = self.read_receipt(command, prior[1], state, authority)
            else:
                if state['revision'] != command.expected_revision:
                    raise Rejected('stale_revision')
                result = self.apply(command, authority, state, now)
                state['revision'] += 1
                result.update(schema_version=1, operation_id=command.operation_id, subject_id=subject,
                              actor_id=command.actor_id, watch_id=None, organization_id=command.organization_id,
                              expected_revision=command.expected_revision, revision=state['revision'],
                              pending_reason='session_revocation' if state['status'] == 'pending' else None,
                              next_actor='identity' if state['status'] == 'pending' else None,
                              next_review_at=self.instant(now + 86400) if state['status'] == 'pending' else None)
                self.db.execute('INSERT OR REPLACE INTO factors VALUES(?,?)', (subject, self.seal(subject, state)))
                self.db.execute('INSERT INTO operations VALUES(?,?,?,?)',
                                (subject, command.operation_id, payload, self.seal(subject, self.receipt(state, authority, result, command))))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
