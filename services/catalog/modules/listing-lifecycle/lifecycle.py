"""Durable lifecycle receipts with a bounded canonical transition boundary."""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone


class Denied(Exception):
    pass


def possession_valid(proof, command, now):
    """Called inside the serialized provider transition, never as a cached grant."""
    try:
        issued, submitted, reviewed = (datetime.fromisoformat(proof[k]) for k in (
            'issued_at', 'submitted_at', 'reviewed_at'))
        return (
            all(t.tzinfo is not None and t.utcoffset() == timedelta(0)
                for t in (issued, submitted, reviewed, now))
            and issued <= submitted < issued + timedelta(hours=24)
            and submitted <= reviewed <= now
            and proof['proof_id'] == command.proof_id
            and proof['subject_id'] == command.subject_id
            and proof['watch_id'] == command.watch_id
            and proof['revision'] == command.expected_revision
            and proof['reviewed'] is True and proof['assignment_current'] is True
            and proof['consumed_by'] in (None, command.operation_id)
        )
    except (KeyError, TypeError, ValueError):
        return False


class Store:
    """Local receipt adapter; contains no stock balance or evidence bytes."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA busy_timeout=1000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS lifecycle_receipts (
          operation_id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lifecycle_outbox (
          operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def get(self, operation_id):
        row = self.db.execute('SELECT request,result FROM lifecycle_receipts WHERE operation_id=?',
                              (operation_id,)).fetchone()
        return (json.loads(row[0]), json.loads(row[1])) if row else None

    def prepare(self, command, responsible_operator_id, now):
        payload = command.payload()
        result = {**payload, 'state': 'pending', 'revision': command.expected_revision,
                  'pending_reason': 'confirmation_required', 'next_actor': 'support',
                  'responsible_operator_id': responsible_operator_id,
                  'next_action': 'resolve_confirmation',
                  'next_review_at': (now + timedelta(hours=24)).isoformat(),
                  'escalate_at': (now + timedelta(hours=48)).isoformat(), 'listing_id': None, 'auction_id': None,
                  'previous_auction_id': None}
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO lifecycle_receipts VALUES(?,?,?)',
                            (command.operation_id, json.dumps(payload), json.dumps(result)))
        request, current = self.get(command.operation_id)
        if request != payload:
            raise Denied('operation_conflict')
        return current

    def finish(self, command, result):
        with self.db:
            self.db.execute("UPDATE lifecycle_receipts SET result=? WHERE operation_id=? AND json_extract(result,'$.state')='pending'",
                            (json.dumps(result), command.operation_id))
            self.db.execute('INSERT OR IGNORE INTO lifecycle_outbox VALUES(?,?)', (
                command.operation_id, json.dumps({'operation_id': command.operation_id,
                                                 'subject_id': command.subject_id,
                                                 'revision': result['revision']})))
        return self.get(command.operation_id)[1]


class Lifecycle:
    def __init__(self, store, authorize, transition, *, responsible_operator_id, clock=None):
        from uuid import UUID
        UUID(responsible_operator_id)
        self.responsible_operator_id = responsible_operator_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store, self.authorize, self.transition = store, authorize, transition

    async def access(self, command):
        # The callback rechecks current identity, business, record and permission.
        if not await asyncio.wait_for(self.authorize(command), timeout=2):
            raise Denied('access_denied')

    async def lookup(self, operation_id, actor_id, organization_id):
        stored = self.store.get(operation_id)
        if not stored:
            raise Denied('not_found')
        request, result = stored
        if request['actor_id'] != actor_id or request['organization_id'] != organization_id:
            raise Denied('not_found')
        from types import SimpleNamespace
        scope = SimpleNamespace(**request)
        await self.access(scope)
        return result

    async def execute(self, command):
        await self.access(command)
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError('invalid_server_time')
        current = self.store.prepare(command, self.responsible_operator_id, now)
        if current['state'] != 'pending':
            return current
        try:
            answer = await asyncio.wait_for(self.transition(command), timeout=2)
        except (TimeoutError, ConnectionError):
            await self.access(command)
            return current
        await self.access(command)
        if not valid_answer(command, answer):
            return current
        result = {**current, **{k: v for k, v in answer.items() if k != 'binding'}}
        result.update(responsible_operator_id=None, next_action=None, escalate_at=None)
        return self.store.finish(command, result)


def valid_answer(command, answer):
    if not isinstance(answer, dict) or answer.get('binding') != command.payload():
        return False
    allowed = {'binding', 'state', 'revision', 'pending_reason', 'next_actor',
               'next_review_at', 'listing_id', 'auction_id', 'previous_auction_id'}
    if set(answer) != allowed or answer['state'] not in ('succeeded', 'denied'):
        return False
    revision = answer['revision']
    if type(revision) is not int or revision < command.expected_revision:
        return False
    if answer['next_actor'] is not None or answer['next_review_at'] is not None:
        return False
    from uuid import UUID

    def identifier(value):
        if not isinstance(value, str) or len(value) != 36:
            return False
        try:
            return str(UUID(value)) == value.lower()
        except ValueError:
            return False

    for key in ('listing_id', 'auction_id', 'previous_auction_id'):
        if answer[key] is not None and not identifier(answer[key]):
            return False
    if answer['state'] == 'denied':
        return (answer['pending_reason'] in ('committed', 'stale_revision', 'possession_required',
                                            'terms_changed', 'ineligible')
                and all(answer[key] is None for key in
                        ('listing_id', 'auction_id', 'previous_auction_id')))
    if (revision <= command.expected_revision or answer['pending_reason'] is not None
            or not identifier(answer['listing_id'])):
        return False
    if (command.kind == 'relist') == (answer['listing_id'] == command.subject_id):
        return False
    if answer['previous_auction_id'] is not None and command.kind != 'pause':
        if (answer['auction_id'] is None
                or answer['auction_id'] == answer['previous_auction_id']):
            return False
    return True


def eligibility(command, source, proof, now):
    """Pure guard for the canonical transition's locked current source facts.

    The provider must check these facts and consume proof in the same serialized
    transition as fencing new sales. This function grants no independent authority.
    """
    required = {'subject_id', 'watch_id', 'organization_id', 'revision', 'availability',
                'payment', 'commitment', 'bid_count', 'winner_id', 'custody', 'status'}
    if not required.issubset(source) or type(source['bid_count']) is not int or type(source['revision']) is not int:
        return 'ineligible'
    if (source.get('subject_id') != command.subject_id
            or source.get('watch_id') != command.watch_id
            or source.get('organization_id') != command.organization_id):
        return 'ineligible'
    if source.get('revision') != command.expected_revision:
        return 'stale_revision'
    if (source.get('availability') != 'unsold'
            or source.get('payment') != 'none'
            or source.get('commitment') != 'none'
            or source.get('bid_count') != 0
            or source.get('winner_id') is not None
            or source.get('custody') != 'seller'):
        return 'committed'
    if source.get('status') not in ('published', 'paused', 'withdrawn', 'unsold'):
        return 'ineligible'
    if not possession_valid(proof, command, now):
        return 'possession_required'
    if command.kind == 'pause':
        return None
    if (source.get('quote_id') != command.quote_id
            or source.get('quote_revision') != command.quote_revision
            or source.get('policy_revision') != command.policy_revision
            or source.get('current_terms_accepted') is not True
            or source.get('facts_current') is not True
            or source.get('pricing_validated') is not True):
        return 'terms_changed'
    return None
