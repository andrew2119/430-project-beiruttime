"""Private saves and durable alert receipts. Composition supplies current authority."""
import json
import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from functools import wraps
from threading import RLock
from pathlib import Path

VERSION = 'communications.saved-watches.v1'
KINDS = frozenset(('price', 'bid', 'ending', 'sold'))


class Failure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed
    except (ValueError, AttributeError, TypeError):
        raise Failure('invalid') from None


@dataclass(frozen=True)
class Watch:
    watch_id: str
    revision: int
    status: str
    title: str | None
    price_minor: int | None
    bid_sequence: int
    scheduled_end: str | None
    occurred_at: str
    cancelled: bool = False
    sample: bool = False

    def validate(self):
        if (self.status not in ('available', 'sold', 'unavailable') or type(self.revision) is not int
                or self.revision < 1 or type(self.bid_sequence) is not int or self.bid_sequence < 0
                or (self.price_minor is not None and (type(self.price_minor) is not int
                    or not 0 <= self.price_minor <= 9007199254740991))):
            raise Failure('unavailable')
        instant(self.occurred_at)
        if type(self.cancelled) is not bool or type(self.sample) is not bool:
            raise Failure('unavailable')
        if self.scheduled_end:
            instant(self.scheduled_end)
        return self


class Providers(Protocol):
    # Implementations must bound calls, authenticate internal consumers and fail closed.
    def authorize(self, actor: str, owner: str) -> bool: ...
    def watch(self, watch_id: str) -> Watch: ...
    def occurrences(self, watch_id: str, after: int, through: int, limit: int) -> dict: ...
    def recovery_assignment(self, notice_id: str) -> tuple[str, str]: ...
    def authorize_recovery(self, actor: str, operator: str, notice_id: str) -> bool: ...
    def deliver(self, notice: dict) -> None: ...


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


class Store:
    def __init__(self, path, providers: Providers):
        self.providers = providers
        self.lock = RLock()
        self.db = sqlite3.connect(path, timeout=2, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        for migration in sorted((Path(__file__).parent / 'migrations').glob('L22_*.sql')):
            self.db.executescript(migration.read_text())

    @serialized
    def close(self):
        self.db.close()

    def authorize(self, actor, owner):
        if not actor or actor != owner or not self.providers.authorize(actor, owner):
            raise Failure('denied')

    def source(self, watch_id):
        source = self.providers.watch(watch_id).validate()
        if source.watch_id != watch_id:
            raise Failure('unavailable')
        previous = self.db.execute('SELECT * FROM l22_observed_sources WHERE watch=?', (watch_id,)).fetchone()
        if previous and source.revision < previous['revision']:
            raise Failure('stale')
        if (previous and source.revision == previous['revision']
                and previous['snapshot'] != json.dumps(source.__dict__, sort_keys=True)):
            raise Failure('conflict')
        snapshot = json.dumps(source.__dict__, sort_keys=True)
        self.db.execute('''INSERT INTO l22_observed_sources VALUES(?,?,?)
            ON CONFLICT(watch) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot
            WHERE excluded.revision > l22_observed_sources.revision''',
                        (watch_id, source.revision, snapshot))
        retained = self.db.execute('SELECT * FROM l22_observed_sources WHERE watch=?', (watch_id,)).fetchone()
        if retained['revision'] > source.revision:
            raise Failure('stale')
        if retained['snapshot'] != snapshot:
            raise Failure('conflict')
        return source

    @serialized
    def lookup(self, actor, owner, operation):
        self.authorize(actor, owner)
        row = self.db.execute('SELECT result FROM l22_operations WHERE owner=? AND operation=?',
                              (owner, operation)).fetchone()
        return json.loads(row['result']) if row else None

    @serialized
    def save(self, actor, owner, watch_id, command):
        self.authorize(actor, owner)
        required = {'schema_version', 'operation_id', 'expected_revision', 'saved', 'alerts'}
        if (set(command) != required or command['schema_version'] != VERSION
                or not isinstance(command['operation_id'], str) or not 1 <= len(command['operation_id']) <= 128
                or not isinstance(watch_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,128}', watch_id)
                or type(command['expected_revision']) is not int or command['expected_revision'] < 0
                or type(command['saved']) is not bool or not isinstance(command['alerts'], list)
                or len(command['alerts']) > 4 or any(not isinstance(x, str) or x not in KINDS for x in command['alerts'])
                or len(set(command['alerts'])) != len(command['alerts'])):
            raise Failure('invalid')
        request = json.dumps([watch_id, command], sort_keys=True)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT * FROM l22_operations WHERE owner=? AND operation=?',
                                    (owner, command['operation_id'])).fetchone()
            if prior:
                if prior['request'] != request:
                    raise Failure('conflict')
                result = json.loads(prior['result'])
            else:
                row = self.db.execute('SELECT * FROM l22_saves WHERE owner=? AND watch=?',
                                      (owner, watch_id)).fetchone()
                revision = row['revision'] if row else 0
                if command['expected_revision'] != revision:
                    raise Failure('stale')
                source_revision = None
                if command['saved'] and (not row or not row['saved']):
                    source = self.source(watch_id)
                    source_revision = source.revision
                    if source.status != 'available':
                        raise Failure('unavailable')
                    self.db.execute('INSERT OR IGNORE INTO l22_sources VALUES(?,?,?)',
                                    (watch_id, source.revision, json.dumps(source.__dict__, sort_keys=True)))
                previous_alerts = set(json.loads(row['alerts'])) if row and row['saved'] else set()
                enabled = set(command['alerts']) if command['saved'] else set()
                added = enabled - previous_alerts
                if added and source_revision is None:
                    source = self.source(watch_id)
                for kind in KINDS - enabled:
                    self.db.execute('DELETE FROM l22_alert_subscriptions WHERE owner=? AND watch=? AND kind=?',
                                    (owner, watch_id, kind))
                    self.db.execute('UPDATE l22_outbox SET delivered=1 WHERE owner=? AND watch=? AND kind=? AND delivered=0',
                                    (owner, watch_id, kind))
                for kind in added:
                    self.db.execute('INSERT INTO l22_alert_subscriptions VALUES(?,?,?,?,?,?)',
                                    (owner, watch_id, kind, revision + 1, source.revision,
                                     json.dumps(source.__dict__, sort_keys=True)))
                self.authorize(actor, owner)
                if not command['saved'] or 'ending' not in command['alerts']:
                    self.db.execute("UPDATE l22_outbox SET delivered=1 WHERE owner=? AND watch=? AND kind='ending' AND delivered=0",
                                    (owner, watch_id))
                if command['saved'] and 'ending' in command['alerts']:
                    self.db.execute('INSERT OR IGNORE INTO l22_ending_subscriptions VALUES(?,?,?)',
                                    (owner, watch_id, revision + 1))
                else:
                    self.db.execute('DELETE FROM l22_ending_subscriptions WHERE owner=? AND watch=?',
                                    (owner, watch_id))
                result = dict(schema_version=VERSION, operation_id=command['operation_id'], subject_id=owner,
                              watch_id=watch_id, actor_id=actor, organization_id=None,
                              expected_revision=revision, source_revision=source_revision, state='saved' if command['saved'] else 'removed',
                              revision=revision + 1, pending_reason=None, next_actor=None, next_review_at=None)
                self.db.execute('INSERT OR REPLACE INTO l22_saves VALUES(?,?,?,?,?)',
                                (owner, watch_id, revision + 1, command['saved'], json.dumps(command['alerts'])))
                self.db.execute('INSERT INTO l22_operations VALUES(?,?,?,?)',
                                (owner, command['operation_id'], request, json.dumps(result)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @serialized
    def record(self, actor, owner, watch_id):
        self.authorize(actor, owner)
        row = self.db.execute('SELECT * FROM l22_saves WHERE owner=? AND watch=?',
                              (owner, watch_id)).fetchone()
        subscription = self.db.execute('SELECT since_revision FROM l22_ending_subscriptions WHERE owner=? AND watch=?',
                                       (owner, watch_id)).fetchone()
        subscriptions = self.db.execute(
            'SELECT kind,since_revision,source_revision FROM l22_alert_subscriptions WHERE owner=? AND watch=?',
            (owner, watch_id)).fetchall()
        return dict(watch_id=watch_id, alert_subscriptions={item['kind']: dict(since_revision=item['since_revision'],
                    source_revision=item['source_revision']) for item in subscriptions}, ending_since_revision=subscription['since_revision'] if subscription else None,
                    revision=row['revision'] if row else 0,
                    saved=bool(row['saved']) if row else False,
                    alerts=json.loads(row['alerts']) if row else [])

    @serialized
    def listing(self, actor, owner, offset=0, limit=20):
        self.authorize(actor, owner)
        if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 100000 or not 1 <= limit <= 50:
            raise Failure('invalid')
        rows = self.db.execute('SELECT * FROM l22_saves WHERE owner=? AND saved=1 ORDER BY watch LIMIT ? OFFSET ?',
                               (owner, limit, offset)).fetchall()
        total = self.db.execute('SELECT count(*) FROM l22_saves WHERE owner=? AND saved=1', (owner,)).fetchone()[0]
        items = []
        for row in rows:
            try:
                source = self.source(row['watch'])
                status, title, price = source.status, source.title, source.price_minor
            except (Failure, TimeoutError):
                status, title, price = 'unavailable', None, None
            items.append(dict(watch_id=row['watch'], revision=row['revision'], saved=True,
                              alerts=json.loads(row['alerts']), status=status, title=title, price_minor=price))
        self.authorize(actor, owner)
        return dict(items=items, total=total, offset=offset, limit=limit)

    @serialized
    def observe(self, watch_id, now):
        """Poll canonical facts; an event is only an invalidation, never authority."""
        at = instant(now)
        source = self.source(watch_id)
        if instant(source.occurred_at) > at:
            raise Failure('unavailable')
        snapshot = json.dumps(source.__dict__, sort_keys=True)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous = self.db.execute('SELECT * FROM l22_sources WHERE watch=?', (watch_id,)).fetchone()
            if previous and source.revision < previous['revision']:
                raise Failure('stale')
            if previous and source.revision == previous['revision'] and previous['snapshot'] != snapshot:
                raise Failure('conflict')
            old = json.loads(previous['snapshot']) if previous else None
            occurrences = []
            if old and source.revision > old['revision']:
                batch = self.providers.occurrences(watch_id, old['revision'], source.revision, 200)
                if (not isinstance(batch, dict) or batch.get('through_revision') != source.revision
                        or not isinstance(batch.get('items'), list) or len(batch['items']) > 200):
                    raise Failure('unavailable')
                seen = set()
                for event in batch['items']:
                    if (set(event) != {'event_id', 'watch_id', 'kind', 'revision', 'occurred_at', 'sample'}
                            or event['watch_id'] != watch_id or event['kind'] not in KINDS - {'ending'}
                            or not isinstance(event['event_id'], str) or not 1 <= len(event['event_id']) <= 128
                            or type(event['revision']) is not int
                            or not old['revision'] < event['revision'] <= source.revision
                            or type(event['sample']) is not bool or instant(event['occurred_at']) > at
                            or event['event_id'] in seen):
                        raise Failure('unavailable')
                    seen.add(event['event_id'])
                    occurrences.append(event)
            if source.status == 'available' and not source.cancelled and source.scheduled_end:
                end = instant(source.scheduled_end)
                if end - timedelta(minutes=30) <= at < end:
                    occurrences.append(dict(event_id=source.scheduled_end, kind='ending',
                                            revision=source.revision, sample=source.sample,
                                            occurred_at=(end - timedelta(minutes=30)).isoformat()))
            self.db.execute('INSERT OR REPLACE INTO l22_sources VALUES(?,?,?)',
                            (watch_id, source.revision, snapshot))
            rows = self.db.execute('SELECT * FROM l22_saves WHERE watch=? AND saved=1', (watch_id,)).fetchall()
            for row in rows:
                for event in occurrences:
                    kind = event['kind']
                    subscription = self.db.execute(
                        'SELECT * FROM l22_alert_subscriptions WHERE owner=? AND watch=? AND kind=?',
                        (row['owner'], watch_id, kind)).fetchone()
                    if (kind in json.loads(row['alerts']) and subscription
                            and (kind == 'ending' or event['revision'] > subscription['source_revision'])):
                        notice_id = json.dumps([row['owner'], watch_id, kind, event['event_id']], separators=(',', ':'))
                        self.db.execute('INSERT OR IGNORE INTO l22_outbox VALUES(?,?,?,?,?,?,?,?,?,0,0,\'\')',
                                        (notice_id, row['owner'], watch_id, kind, event['revision'], row['revision'],
                                         event['occurred_at'], source.scheduled_end if kind == 'ending' else None,
                                         event['sample']))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @serialized
    def dispatch(self, now, limit=50):
        instant(now)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise Failure('invalid')
        unassigned = self.db.execute("""SELECT o.* FROM l22_outbox o LEFT JOIN l22_recovery r
            ON r.notice_id=o.notice_id WHERE o.delivered=0 AND o.attempts>=5 AND r.notice_id IS NULL
            ORDER BY o.attempted_at,o.notice_id LIMIT ?""", (limit,)).fetchall()
        for row in unassigned:
            try:
                assignment = self.providers.recovery_assignment(row['notice_id'])
                if (not isinstance(assignment, tuple) or len(assignment) != 2
                        or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in assignment)):
                    raise Failure('unavailable')
                at = instant(row['attempted_at'])
                self.db.execute("""INSERT OR IGNORE INTO l22_recovery
                    VALUES(?,?,?,'review_delivery',?,?,?,NULL,NULL,'held',1)""",
                    (row['notice_id'], *assignment, row['attempted_at'],
                     (at + timedelta(hours=24)).isoformat(), (at + timedelta(hours=48)).isoformat()))
            except (Failure, TimeoutError):
                continue
        self.advance_recovery(now, limit)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise Failure('invalid')
        rows = self.db.execute("""SELECT * FROM l22_outbox WHERE delivered=0 AND attempts<5
            ORDER BY attempted_at,notice_id LIMIT ?""", (limit,)).fetchall()
        pending = delivered = 0
        for row in rows:
            assignment = None
            if row['attempts'] == 4:
                try:
                    assignment = self.providers.recovery_assignment(row['notice_id'])
                    if (not isinstance(assignment, tuple) or len(assignment) != 2
                            or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in assignment)):
                        raise Failure('unavailable')
                except (Failure, TimeoutError):
                    pending += 1
                    continue
            try:
                self.authorize(row['owner'], row['owner'])
                source = self.source(row['watch'])
                saved = self.db.execute('SELECT * FROM l22_saves WHERE owner=? AND watch=?',
                                        (row['owner'], row['watch'])).fetchone()
                subscription = self.db.execute(
                    'SELECT * FROM l22_alert_subscriptions WHERE owner=? AND watch=? AND kind=?',
                    (row['owner'], row['watch'], row['kind'])).fetchone()
                valid = (saved and saved['saved'] and subscription
                         and subscription['since_revision'] <= row['save_revision'] <= saved['revision']
                         and row['kind'] in json.loads(saved['alerts']))
                if row['kind'] == 'ending':
                    subscription = self.db.execute('SELECT since_revision FROM l22_ending_subscriptions WHERE owner=? AND watch=?',
                                                   (row['owner'], row['watch'])).fetchone()
                    valid = (valid and subscription and subscription['since_revision'] <= row['save_revision'])
                    valid = (valid and source.status == 'available' and not source.cancelled
                             and source.revision >= row['source_revision']
                             and source.scheduled_end == row['scheduled_end']
                             and source.scheduled_end and instant(now) < instant(source.scheduled_end))
                elif row['kind'] == 'sold':
                    valid = valid and source.status == 'sold' and source.revision >= row['source_revision']
                else:
                    valid = (valid and source.status == 'available' and not source.cancelled
                             and source.revision >= row['source_revision'])
                if valid:
                    self.providers.deliver(dict(notice_id=row['notice_id'], owner_id=row['owner'], watch_id=row['watch'],
                                                kind=row['kind'], source_revision=row['source_revision'],
                                                save_revision=row['save_revision'], scheduled_end=row['scheduled_end'],
                                                occurred_at=row['occurred_at'], required=False, sample=bool(row['sample']),
                                                destination='/watches/' + row['watch']))
                    delivered += 1
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    self.db.execute('UPDATE l22_outbox SET delivered=1 WHERE notice_id=?', (row['notice_id'],))
                    self.db.execute("UPDATE l22_recovery SET state='resolved',revision=revision+1 WHERE notice_id=? AND state!='resolved'",
                                    (row['notice_id'],))
                    self.db.execute('COMMIT')
                except BaseException:
                    self.db.execute('ROLLBACK')
                    raise
            except (Failure, TimeoutError):
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    self.db.execute('UPDATE l22_outbox SET attempted_at=?,attempts=attempts+1 WHERE notice_id=?',
                                    (now, row['notice_id']))
                    if assignment:
                        at = instant(now)
                        self.db.execute("""INSERT OR IGNORE INTO l22_recovery
                            VALUES(?,?,?,'review_delivery',?,?,?,NULL,NULL,'held',1)""",
                            (row['notice_id'], *assignment, now, (at + timedelta(hours=24)).isoformat(),
                             (at + timedelta(hours=48)).isoformat()))
                    self.db.execute('COMMIT')
                except BaseException:
                    self.db.execute('ROLLBACK')
                    raise
                pending += 1
        held = self.db.execute('SELECT count(*) FROM l22_outbox WHERE delivered=0 AND attempts>=5').fetchone()[0]
        return dict(delivered=delivered, pending=pending, held=held,
                    next_actor='communications_support' if held else None)


    @serialized
    def advance_recovery(self, now, limit=50):
        at = instant(now)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise Failure('invalid')
        rows = self.db.execute("SELECT * FROM l22_recovery WHERE state='held' ORDER BY held_at,notice_id LIMIT ?",
                               (limit,)).fetchall()
        for row in rows:
            if at >= instant(row['escalate_at']):
                self.db.execute("""UPDATE l22_recovery SET operator=escalation_operator,
                    next_action='escalated_review',escalated_at=?,state='escalated',revision=revision+1
                    WHERE notice_id=? AND state='held'""", (now, row['notice_id']))
            elif at >= instant(row['response_due']) and row['responded_at'] is None:
                self.db.execute("UPDATE l22_recovery SET next_action='response_overdue' WHERE notice_id=?",
                                (row['notice_id'],))

    @serialized
    def recovery(self, actor, notice_id):
        row = self.db.execute('SELECT * FROM l22_recovery WHERE notice_id=?', (notice_id,)).fetchone()
        if not row or not self.providers.authorize_recovery(actor, row['operator'], notice_id):
            raise Failure('denied')
        return dict(row)

    @serialized
    def reconcile(self, actor, notice_id, operation, expected_revision, now):
        """An assigned current operator records a response and permits one bounded retry cycle."""
        instant(now)
        if (not isinstance(operation, str) or not 1 <= len(operation) <= 128
                or type(expected_revision) is not int or expected_revision < 1):
            raise Failure('invalid')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.recovery(actor, notice_id)
            request = json.dumps([notice_id, expected_revision, now])
            prior = self.db.execute('SELECT * FROM l22_reconciliation WHERE actor=? AND operation=?',
                                    (actor, operation)).fetchone()
            if prior:
                if prior['request'] != request:
                    raise Failure('conflict')
                result = json.loads(prior['result'])
            else:
                outbox = self.db.execute('SELECT attempts,delivered FROM l22_outbox WHERE notice_id=?',
                                         (notice_id,)).fetchone()
                if (row['revision'] != expected_revision or row['state'] == 'resolved'
                        or not outbox or outbox['delivered'] or outbox['attempts'] < 5):
                    raise Failure('stale')
                self.db.execute("""UPDATE l22_recovery SET responded_at=?,next_action='retry_delivery',
                    revision=revision+1 WHERE notice_id=?""", (now, notice_id))
                self.db.execute('UPDATE l22_outbox SET attempts=0 WHERE notice_id=? AND delivered=0', (notice_id,))
                result = dict(notice_id=notice_id, operation_id=operation, revision=expected_revision + 1,
                              state='pending', next_action='retry_delivery')
                self.db.execute('INSERT INTO l22_reconciliation VALUES(?,?,?,?)',
                                (actor, operation, request, json.dumps(result)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
