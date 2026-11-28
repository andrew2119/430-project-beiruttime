"""Durable review commands. Composition supplies fresh authority and source facts."""
import json
import re
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone


class Refused(ValueError):
    pass


class Reviews:
    def __init__(self, path, authority, purchase, clock=lambda: datetime.now(timezone.utc)):
        self.authority, self.purchase, self.clock = authority, purchase, clock
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS l18_reviews (
          id TEXT PRIMARY KEY, seller TEXT NOT NULL, buyer TEXT NOT NULL,
          organization TEXT NOT NULL, watch TEXT NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
          text TEXT NOT NULL, reply TEXT, reply_author TEXT, visible INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS l18_reports (
          review TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL,
          PRIMARY KEY(review, reporter));
        CREATE TABLE IF NOT EXISTS l18_decisions (
          review TEXT NOT NULL, moderator TEXT NOT NULL, reason TEXT NOT NULL, visible INTEGER NOT NULL, revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS l18_receipts (
          operation TEXT PRIMARY KEY, actor TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l18_outbox (
          operation TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')

        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(l18_reviews)')}
        if 'reply_author' not in columns:
            self.db.execute('ALTER TABLE l18_reviews ADD COLUMN reply_author TEXT')

        if 'review_ref' not in columns:
            self.db.execute('ALTER TABLE l18_reviews ADD COLUMN review_ref TEXT')
        self.db.execute('UPDATE l18_reviews SET review_ref=lower(hex(randomblob(16))) WHERE review_ref IS NULL')
        self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS l18_review_ref ON l18_reviews(review_ref)')

    def subject(self, reference):
        row = self.db.execute('SELECT id FROM l18_reviews WHERE review_ref=?', (reference,)).fetchone()
        return row['id'] if row else reference

    def current(self, actor, organization, subject):
        # The supplied boundary must enforce a bounded call and current record scope.
        try:
            access = self.authority(actor, organization, subject)
        except Exception:
            raise Refused('unavailable') from None
        if not isinstance(access, dict):
            raise Refused('unavailable')
        if not access or not access.get('active') or access.get('subject_id') != subject or access.get('actor_id') != actor or access.get('organization_id') != organization:
            raise Refused('scope_denied')
        return access

    def command(self, c):
        required = ('operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id',
                    'expected_revision', 'source_revision', 'quote_revision', 'policy_revision', 'kind')
        if not isinstance(c, dict):
            raise Refused('invalid_command')
        if set(c) - set(required) - {'rating', 'text', 'reason', 'visible'}:
            raise Refused('invalid_command')
        if any(k not in c for k in required) or len(json.dumps(c, ensure_ascii=False)) > 24000:
            raise Refused('invalid_command')
        if any(not isinstance(c[k], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', c[k])
               for k in required[:5]):
            raise Refused('invalid_reference')
        if any(type(c[k]) is not int or not 0 <= c[k] <= 2147483647 for k in required[5:9]):
            raise Refused('invalid_revision')
        payload = json.dumps(c, sort_keys=True, ensure_ascii=False)
        reference = c['subject_id']
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if c['kind'] == 'report':
                c = {**c, 'subject_id': self.subject(reference)}
            access = self.current(c['actor_id'], c['organization_id'], c['subject_id'])
            try:
                source = self.purchase(c['subject_id'])
            except Exception:
                raise Refused('unavailable') from None
            keys = ('purchase_id', 'watch_id', 'organization_id', 'buyer_id', 'seller_id', 'state', 'source_revision', 'quote_revision', 'policy_revision')
            if not isinstance(source, dict) or any(k not in source for k in keys):
                raise Refused('unavailable')
            if (source['purchase_id'] != c['subject_id'] or source['watch_id'] != c['watch_id']
                    or source['organization_id'] != c['organization_id']):
                raise Refused('scope_denied')
            prior = self.db.execute('SELECT * FROM l18_receipts WHERE operation=?', (c['operation_id'],)).fetchone()
            if prior:
                if prior['actor'] != c['actor_id'] or prior['payload'] != payload:
                    raise Refused('operation_conflict')
                result = json.loads(prior['result'])
            else:
                result = {**self.apply(c, source, access), 'subject_id': reference}
                self.db.execute('INSERT INTO l18_receipts VALUES(?,?,?,?)',
                                (c['operation_id'], c['actor_id'], payload, json.dumps(result)))
                # Public event carries no text, identities, report or decision reasons.
                self.db.execute('INSERT INTO l18_outbox VALUES(?,?)', (c['operation_id'], json.dumps({
                    'schema_version': 'transaction-reviews.v1', 'subject_id': c['subject_id'],
                    'revision': result['revision']})))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def apply(self, c, source, access):
        if any(source[k] != c[k] for k in ('source_revision', 'quote_revision', 'policy_revision')):
            raise Refused('stale_revision')
        row = self.db.execute('SELECT * FROM l18_reviews WHERE id=?', (c['subject_id'],)).fetchone()
        revision = row['revision'] if row else 0
        if revision != c['expected_revision']:
            raise Refused('stale_revision')
        kind, actor = c['kind'], c['actor_id']
        if kind == 'create':
            if source['state'] != 'released':
                raise Refused('purchase_not_released')
            try:
                released = datetime.fromisoformat(source['released_at'].replace('Z', '+00:00'))
            except (KeyError, AttributeError, TypeError, ValueError):
                raise Refused('unavailable') from None
            if released.utcoffset() is None or released > self.clock() or source['state'] != 'released':
                raise Refused('purchase_not_released')
            if actor != source['buyer_id'] or actor == source['seller_id'] or access.get('seller_id') == source['seller_id'] or row:
                raise Refused('review_denied')
            if type(c.get('rating')) is not int or not 1 <= c['rating'] <= 5:
                raise Refused('invalid_rating')
            text = self.text(c, 'text', 2000)
            self.db.execute('INSERT INTO l18_reviews (id,seller,buyer,organization,watch,rating,text,reply,visible,revision,review_ref) VALUES(?,?,?,?,?,?,?,NULL,1,1,?)', (
                c['subject_id'], source['seller_id'], actor, c['organization_id'], c['watch_id'], c['rating'], text, uuid4().hex))
        elif row is None:
            raise Refused('review_missing')
        elif kind == 'reply':
            if not access.get('seller_reply') or access.get('seller_id') != row['seller'] or actor == row['buyer'] or row['reply'] is not None:
                raise Refused('reply_denied')
            self.db.execute('UPDATE l18_reviews SET reply=?, reply_author=?, revision=revision+1 WHERE id=?',
                            (self.text(c, 'text', 2000), actor, c['subject_id']))
        elif kind == 'report':
            reason = self.text(c, 'reason', 1000)
            if self.db.execute('SELECT 1 FROM l18_reports WHERE review=? AND reporter=?', (row['id'], actor)).fetchone():
                raise Refused('duplicate_report')
            self.db.execute('INSERT INTO l18_reports VALUES(?,?,?)', (row['id'], actor, reason))
            self.db.execute('UPDATE l18_reviews SET revision=revision+1 WHERE id=?', (row['id'],))
        elif kind == 'decide':
            reporters = [r[0] for r in self.db.execute('SELECT reporter FROM l18_reports WHERE review=?', (row['id'],))]
            if (not reporters or access.get('assigned_review') != row['id'] or not access.get('moderate')
                    or (row['reply'] is not None and row['reply_author'] is None)
                    or actor in [row['buyer'], row['seller'], row['reply_author'], *reporters] or access.get('seller_id') == row['seller']):
                raise Refused('independent_assignment_required')
            reason = self.text(c, 'reason', 1000)
            if type(c.get('visible')) is not bool:
                raise Refused('invalid_decision')
            self.db.execute('INSERT INTO l18_decisions VALUES(?,?,?,?,?)', (row['id'], actor, reason, c['visible'], revision + 1))
            self.db.execute('UPDATE l18_reviews SET visible=?,revision=revision+1 WHERE id=?', (c['visible'], row['id']))
        else:
            raise Refused('unknown_command')
        return {**{k: c[k] for k in ('operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision')},
                'schema_version': 'transaction-reviews.v1', 'state': 'confirmed', 'revision': revision + 1,
                'pending_reason': None, 'next_actor': None, 'next_review_at': None}

    @staticmethod
    def text(c, key, bound):
        value = c.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > bound:
            raise Refused('invalid_text')
        return value

    def lookup(self, operation, actor, organization, subject):
        self.current(actor, organization, self.subject(subject))
        row = self.db.execute('SELECT * FROM l18_receipts WHERE operation=? AND actor=?', (operation, actor)).fetchone()
        if row is None:
            return None
        result = json.loads(row['result'])
        if result['subject_id'] != subject or result['organization_id'] != organization:
            raise Refused('scope_denied')
        return result

    def public(self, seller, page=1):
        if type(page) is not int or page < 1:
            raise Refused('invalid_page')
        counts = [self.db.execute('SELECT count(*) FROM l18_reviews WHERE seller=? AND visible=1 AND rating=?', (seller, n)).fetchone()[0] for n in range(1, 6)]
        total = sum(counts)
        rows = self.db.execute('SELECT review_ref,rating,text,reply FROM l18_reviews WHERE seller=? AND visible=1 ORDER BY id LIMIT 20 OFFSET ?', (seller, (page-1)*20))
        return {'items': [dict(r) for r in rows], 'total': total, 'distribution': counts,
                'average': sum((i+1)*n for i, n in enumerate(counts))/total if total else None,
                'page': page, 'next_page': page+1 if page*20 < total else None}
