"""Atomic private review receipts; source authority is supplied by a current lease."""
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone


class Rejected(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def authorize(context, command, now):
    required = ('actor_id', 'organization_id', 'subject_id', 'watch_id', 'seller_id')
    if any(not isinstance(context.get(key), str) or not context[key].strip() for key in required):
        raise Rejected('denied')
    parties = context.get('parties')
    if (not isinstance(parties, (list, tuple)) or not parties
            or any(not isinstance(party, str) or not party.strip() for party in parties)
            or not {context['subject_id'], context['seller_id']}.issubset(parties)):
        raise Rejected('denied')
    if any(context.get(key) != command.get(key) for key in ('organization_id', 'subject_id', 'watch_id')):
        raise Rejected('denied')
    if (not context.get('actor_id') or not context.get('assigned') or not context.get('permitted')
            or context['actor_id'] in parties):
        raise Rejected('denied')
    if context.get('valid_until', now) <= now:
        raise Rejected('unavailable')


def detect(photos, bids, watch_id, now, seller_id):
    if len(photos) > 500 or len(bids) > 5000:
        raise Rejected('invalid')
    photo_ids, bid_ids = {}, {}
    hashes = defaultdict(set)
    target = set()
    for photo in photos:
        prior = photo_ids.setdefault(photo['photo_id'], photo)
        if prior != photo:
            raise Rejected('invalid')
        if photo['normalization_version'] != 'v1':
            raise Rejected('invalid')
        digest = photo['normalized_hash']
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise Rejected('invalid')
        hashes[digest].add(photo['watch_id'])
        if photo['watch_id'] == watch_id:
            target.add(digest)
    pairs = defaultdict(set)
    for bid in bids:
        prior = bid_ids.setdefault(bid['bid_id'], bid)
        if prior != bid:
            raise Rejected('invalid')
        instant = datetime.fromisoformat(bid['accepted_at'].replace('Z', '+00:00'))
        if instant.tzinfo is None or instant > now:
            raise Rejected('invalid')
        if bid['seller_id'] == seller_id and not bid['automatic'] and now - timedelta(days=30) <= instant <= now:
            pairs[(bid['bidder_id'], bid['seller_id'])].add(bid['auction_id'])
    reused = sum(len(hashes[digest] - {watch_id}) for digest in target)
    reasons = []
    if reused:
        reasons.append({'kind': 'exact_photo_reuse', 'count': reused})
    repeated = sum(1 for auctions in pairs.values() if len(auctions) >= 3)
    if repeated:
        reasons.append({'kind': 'repeated_pair', 'count': repeated})
    return reasons


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=1.2, isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS l19_signal_subjects (
          organization TEXT NOT NULL, subject TEXT NOT NULL, watch TEXT NOT NULL,
          revision INTEGER NOT NULL, PRIMARY KEY(organization,subject,watch));
        CREATE TABLE IF NOT EXISTS l19_signal_operations (
          operation TEXT PRIMARY KEY, actor TEXT NOT NULL, organization TEXT NOT NULL,
          subject TEXT NOT NULL, watch TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def scan(self, command, context, photos, bids, now):
        authorize(context, command, now)
        if any(bid['bidder_id'] not in context['parties'] for bid in bids):
            raise Rejected('denied')
        if context['source_revision'] != command['source_revision']:
            raise Rejected('stale')
        digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT actor,digest,result FROM l19_signal_operations WHERE operation=?',
                                  (command['operation_id'],)).fetchone()
            if row:
                if row[0] != context['actor_id']:
                    raise Rejected('denied')
                if row[1] != digest:
                    raise Rejected('conflict')
                result = json.loads(row[2])
            else:
                scope = (command['organization_id'], command['subject_id'], command['watch_id'])
                row = self.db.execute('SELECT revision FROM l19_signal_subjects WHERE organization=? AND subject=? AND watch=?', scope).fetchone()
                revision = row[0] if row else 0
                if command['expected_revision'] != revision or context['record_revision'] != revision:
                    raise Rejected('stale')
                reasons = detect(photos, bids, command['watch_id'], now, context['seller_id'])
                result = {**command, 'actor_id': context['actor_id'], 'revision': revision + 1,
                          'state': 'review_required' if reasons else 'no_observable_signal',
                          'reasons': reasons, 'pending_reason': None,
                          'next_actor': context['actor_id'],
                          'next_review_at': (now + timedelta(hours=24)).astimezone(timezone.utc).isoformat()}
                self.db.execute('INSERT INTO l19_signal_subjects VALUES(?,?,?,?) ON CONFLICT(organization,subject,watch) DO UPDATE SET revision=excluded.revision', (*scope, revision + 1))
                self.db.execute('INSERT INTO l19_signal_operations VALUES(?,?,?,?,?,?,?)',
                                (command['operation_id'], context['actor_id'], *scope, digest, json.dumps(result)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def lookup(self, operation_id, context, now):
        row = self.db.execute('SELECT result FROM l19_signal_operations WHERE operation=?', (operation_id,)).fetchone()
        if not row:
            raise Rejected('denied')
        result = json.loads(row[0])
        authorize(context, result, now)
        return result

    def page(self, context, now, page=1, page_size=20):
        authorize(context, context, now)
        if type(page) is not int or type(page_size) is not int or not 1 <= page <= 100000 or not 1 <= page_size <= 50:
            raise Rejected('invalid')
        scope = (context['organization_id'], context['subject_id'], context['watch_id'])
        where = ' FROM l19_signal_operations WHERE organization=? AND subject=? AND watch=?'
        total = self.db.execute('SELECT count(*)' + where, scope).fetchone()[0]
        rows = self.db.execute('SELECT result' + where + ' ORDER BY operation LIMIT ? OFFSET ?', (*scope, page_size, (page - 1) * page_size)).fetchall()
        return {'items': [json.loads(row[0]) for row in rows], 'total': total, 'page': page, 'page_size': page_size}
