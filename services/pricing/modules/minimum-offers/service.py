"""Private rule persistence; runtime composition supplies the serialized provider."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

LIMIT = 9007199254740991
FIELDS = {'schema_version', 'operation_id', 'actor_id', 'organization_id',
          'subject_id', 'watch_id', 'expected_revision', 'source_revision',
          'policy_revision', 'quote_id', 'quote_revision', 'minimum_minor'}


@dataclass(frozen=True)
class Facts:
    actor_id: str
    organization_id: str
    subject_id: str
    watch_id: str
    source_revision: int
    policy_revision: int
    quote_id: str
    quote_revision: int
    active: bool
    permitted: bool
    mode: str
    committed: bool


class MinimumOffers:
    def __init__(self, database, provider):
        self.database, self.provider = database, provider
        with self.transaction() as db:
            db.executescript((Path(__file__).parent / 'migrations/L18_0001_minimum_offers.sql').read_text())

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.database, timeout=2, isolation_level=None)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def valid(command):
        if not isinstance(command, dict) or set(command) != FIELDS:
            return False
        if len(json.dumps(command).encode()) > 4096:
            return False
        for key in FIELDS - {'schema_version', 'minimum_minor', 'expected_revision',
                             'source_revision', 'policy_revision', 'quote_revision'}:
            if not isinstance(command[key], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', command[key]):
                return False
        for key in ('expected_revision', 'source_revision', 'policy_revision', 'quote_revision'):
            if type(command[key]) is not int or not 0 <= command[key] <= LIMIT:
                return False
        amount = command['minimum_minor']
        return (type(command['schema_version']) is int and command['schema_version'] == 1
                and (amount is None or type(amount) is int and 0 < amount <= LIMIT))

    @staticmethod
    def authorized(command, actor, facts):
        return (facts.active and facts.permitted and actor == facts.actor_id == command['actor_id']
                and all(getattr(facts, key) == command[key] for key in
                        ('organization_id', 'subject_id', 'watch_id')))

    @staticmethod
    def bound(command, facts):
        return all(getattr(facts, key) == command[key] for key in
                   ('source_revision', 'policy_revision', 'quote_id', 'quote_revision'))

    @staticmethod
    def response(command, state, **extra):
        result = dict(schema_version=1, operation_id=command.get('operation_id', ''), state=state)
        if state != 'denied':
            result.update({key: command[key] for key in
                           ('subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision')})
            result.update(revision=None, pending_reason=None, next_actor=None, next_review_at=None)
        result.update(extra)
        return result

    def save(self, command, actor):
        if not self.valid(command):
            return {'schema_version': 1, 'operation_id': '', 'state': 'denied'}
        denied = self.response(command, 'denied')
        try:
            with self.provider.locked(command, actor, timeout_seconds=2) as facts:
                if not self.authorized(command, actor, facts):
                    return denied
                with self.transaction() as db:
                    encoded = json.dumps(command, sort_keys=True, separators=(',', ':'))
                    receipt = db.execute('SELECT command,result FROM l18_minimum_receipts WHERE operation=?',
                                         (command['operation_id'],)).fetchone()
                    if receipt:
                        return json.loads(receipt[1]) if receipt[0] == encoded else denied
                    if facts.committed or facts.mode != 'fixed_price':
                        return denied
                    if not self.bound(command, facts):
                        return self.response(command, 'stale')
                    row = db.execute('SELECT watch,organization,revision FROM l18_minimum_rules WHERE subject=?',
                                     (command['subject_id'],)).fetchone()
                    if row and row[:2] != (facts.watch_id, facts.organization_id):
                        return denied
                    revision = row[2] if row else 0
                    if revision != command['expected_revision']:
                        return self.response(command, 'stale', revision=revision)
                    revision += 1
                    result = self.response(command, 'saved', revision=revision, minimum_minor=command['minimum_minor'])
                    db.execute('INSERT OR REPLACE INTO l18_minimum_rules VALUES (?,?,?,?,?)',
                               (facts.subject_id, facts.watch_id, facts.organization_id, revision, command['minimum_minor']))
                    db.execute('INSERT INTO l18_minimum_receipts VALUES (?,?,?)',
                               (command['operation_id'], encoded, json.dumps(result)))
                    event = dict(type='minimum-offers.changed.v1', operation_id=command['operation_id'],
                                 subject_id=facts.subject_id, watch_id=facts.watch_id, revision=revision)
                    db.execute('INSERT INTO l18_minimum_outbox VALUES (?,?)', (command['operation_id'], json.dumps(event)))
                    return result
        except (TimeoutError, ConnectionError, sqlite3.OperationalError):
            return self.response(command, 'pending', pending_reason='source_unavailable',
                                 next_actor='seller', next_review_at=None)

    def read(self, command, actor, operation=False):
        if not self.valid(command):
            return {'state': 'denied'}
        try:
            with self.provider.locked(command, actor, timeout_seconds=2) as facts:
                if not self.authorized(command, actor, facts):
                    return self.response(command, 'denied')
                with self.transaction() as db:
                    if operation:
                        row = db.execute('SELECT command,result FROM l18_minimum_receipts WHERE operation=?',
                                         (command['operation_id'],)).fetchone()
                        if row:
                            original = json.loads(row[0])
                            if any(original[k] != command[k] for k in ('actor_id', 'organization_id', 'subject_id', 'watch_id')):
                                return self.response(command, 'denied')
                            return json.loads(row[1])
                        return self.response(command, 'unavailable')
                    row = db.execute('SELECT revision,minimum FROM l18_minimum_rules WHERE subject=? AND watch=? AND organization=?',
                                     (facts.subject_id, facts.watch_id, facts.organization_id)).fetchone()
                    return self.response(command, 'saved', revision=row[0] if row else 0,
                                         minimum_minor=row[1] if row else None)
        except (TimeoutError, ConnectionError, sqlite3.OperationalError):
            return self.response(command, 'unavailable')

    def evaluate(self, db, facts, buyer_id, amount_minor):
        """Internal only: caller holds current canonical offer admission fence.

        The authenticated producer supplies exact retained cents and current buyer
        scope. This method neither admits an offer nor writes an agreement.
        """
        if type(amount_minor) is not int or not 0 < amount_minor <= LIMIT:
            raise ValueError('invalid_amount')
        if not facts.active or not facts.permitted or facts.committed or facts.mode != 'fixed_price' or buyer_id == facts.actor_id:
            raise PermissionError('unavailable')
        blocked = db.execute('SELECT 1 FROM l18_offer_blocks WHERE (owner=? AND other=?) OR (owner=? AND other=?)',
                             (facts.actor_id, buyer_id, buyer_id, facts.actor_id)).fetchone()
        row = db.execute('SELECT minimum FROM l18_minimum_rules WHERE subject=? AND watch=? AND organization=?',
                         (facts.subject_id, facts.watch_id, facts.organization_id)).fetchone()
        return {'state': 'declined' if blocked or row and row[0] is not None and amount_minor < row[0] else 'review_required'}

    @staticmethod
    def set_own_block(db, authenticated_actor, other, blocked):
        if authenticated_actor == other or not authenticated_actor or not other:
            raise ValueError('invalid_scope')
        if blocked:
            db.execute('INSERT OR IGNORE INTO l18_offer_blocks VALUES (?,?)', (authenticated_actor, other))
        else:
            db.execute('DELETE FROM l18_offer_blocks WHERE owner=? AND other=?', (authenticated_actor, other))
