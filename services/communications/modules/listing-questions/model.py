"""Durable listing questions with current scoped authorization supplied by the host."""
import asyncio
import json
import re
import sqlite3
from pathlib import Path
import unicodedata
from datetime import datetime, timezone


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def sensitive(text):
    return bool(re.search(r'@|https?://|www\.|(?:\+?\d[\s().-]*){7,}|serial|passport|هوية|جواز|هاتف', text, re.I))


class Rejected(Exception):
    pass


class Questions:
    def __init__(self, database, authority, assessment=None):
        self.authority = authority
        self.assessment = assessment
        self.db = sqlite3.connect(database, isolation_level=None, timeout=0.2)
        self.db.row_factory = sqlite3.Row
        self.db.executescript((Path(__file__).parent / 'migrations/L18_0001_listing_questions.sql').read_text())

    async def access(self, actor, organization, listing):
        try:
            scope = await asyncio.wait_for(self.authority(actor, organization, listing), 1.2)
        except (TimeoutError, OSError):
            raise Rejected('unavailable') from None
        if not isinstance(scope, dict) or type(scope.get('allowed')) is not bool:
            raise Rejected('unavailable')
        if not scope['allowed']:
            raise Rejected('denied')
        if any(not isinstance(scope.get(key), str) or not scope[key] for key in ('watch_id', 'seller_id')) or type(scope.get('revision')) is not int or scope['revision'] < 0:
            raise Rejected('unavailable')
        for permission in ('can_ask', 'can_answer', 'can_report', 'assigned_moderator'):
            if permission in scope and type(scope[permission]) is not bool:
                raise Rejected('unavailable')
        assignments = scope.get('assigned_question_ids', [])
        if not isinstance(assignments, list) or len(assignments) > 1000 or any(not isinstance(key, str) or not 1 <= len(key) <= 200 for key in assignments):
            raise Rejected('unavailable')
        return scope

    async def listing(self, actor, organization, listing, page=0, match=None):
        scope = await self.access(actor, organization, listing)
        if type(page) is not int or not 0 <= page <= 50000:
            raise Rejected('invalid')
        where = "listing=? AND watch=? AND state='published'"
        args = [listing, scope['watch_id']]
        if match is not None:
            if not isinstance(match, str) or len(match) > 2000:
                raise Rejected('invalid')
            where += " AND answer IS NOT NULL AND normalized=?"
            args.append(normalized(match))
        total = self.db.execute('SELECT count(*) FROM l18_questions WHERE ' + where, args).fetchone()[0]
        rows = self.db.execute('SELECT * FROM l18_questions WHERE ' + where + ' ORDER BY id LIMIT 20 OFFSET ?', [*args, page*20]).fetchall()
        return {'items': [self.public(r) for r in rows], 'total': total, 'page': page, 'watch_id': scope['watch_id'], 'source_revision': scope['revision'], 'can_answer': actor == scope['seller_id'] and scope.get('can_answer') is True, 'can_moderate': scope.get('assigned_moderator') is True and bool(scope.get('assigned_question_ids')), 'assigned_question_ids': scope.get('assigned_question_ids', []) if actor and scope.get('assigned_moderator') is True else []}

    async def review(self, actor, organization, listing, question, reports_page=0, appeals_page=0):
        scope = await self.access(actor, organization, listing)
        if scope.get('assigned_moderator') is not True or question not in scope.get('assigned_question_ids', []):
            raise Rejected('denied')
        row = self.db.execute('SELECT * FROM l18_questions WHERE id=? AND listing=? AND watch=?', (question, listing, scope['watch_id'])).fetchone()
        reported = self.db.execute('SELECT 1 FROM l18_reports WHERE question=? AND reporter=? LIMIT 1', (question, actor)).fetchone()
        if not row or actor in (row['author'], row['seller']) or reported:
            raise Rejected('denied')
        if any(type(page) is not int or not 0 <= page <= 50000 for page in (reports_page, appeals_page)):
            raise Rejected('invalid')
        reports_total = self.db.execute('SELECT count(*) FROM l18_reports WHERE question=?', (question,)).fetchone()[0]
        appeals_total = self.db.execute('SELECT count(*) FROM l18_appeals WHERE question=?', (question,)).fetchone()[0]
        reports = self.db.execute('SELECT reason,created_at FROM l18_reports WHERE question=? ORDER BY created_at DESC,operation DESC LIMIT 20 OFFSET ?', (question, reports_page*20)).fetchall()
        appeals = self.db.execute('SELECT reason,created_at FROM l18_appeals WHERE question=? ORDER BY created_at DESC,operation DESC LIMIT 20 OFFSET ?', (question, appeals_page*20)).fetchall()
        return dict(self.public(row), state=row['state'], reports_total=reports_total, reports_page=reports_page, appeals_total=appeals_total, appeals_page=appeals_page, reports=[dict(r) for r in reports], appeals=[dict(r) for r in appeals])

    @staticmethod
    def public(row):
        return {k: row[k] for k in ('id', 'question', 'answer', 'seller', 'revision')}

    async def lookup(self, actor, organization, listing, operation):
        await self.access(actor, organization, listing)
        row = self.db.execute('SELECT * FROM l18_receipts WHERE operation=?', (operation,)).fetchone()
        if not row:
            return {'state': 'pending', 'operation_id': operation}
        binding = json.loads(row['binding'])
        if (binding['actor_id'], binding['organization_id'], binding['listing_id']) != (actor, organization, listing):
            raise Rejected('denied')
        return json.loads(row['result'])

    async def command(self, actor, organization, listing, body):
        scope = await self.access(actor, organization, listing)
        required = {'operation_id', 'kind', 'watch_id', 'source_revision', 'expected_revision', 'question_id', 'text'}
        if not isinstance(body, dict) or set(body) != required or body['kind'] not in ('ask', 'answer', 'report', 'hide', 'appeal'):
            raise Rejected('invalid')
        if any(not isinstance(body[k], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', body[k]) for k in ('operation_id', 'question_id', 'watch_id')):
            raise Rejected('invalid')
        text = body['text']
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise Rejected('invalid')
        if any(type(body[k]) is not int or body[k] < 0 for k in ('source_revision', 'expected_revision')):
            raise Rejected('invalid')
        permission = {'ask': 'can_ask', 'answer': 'can_answer', 'report': 'can_report', 'hide': 'assigned_moderator', 'appeal': 'can_report'}[body['kind']]
        if scope.get(permission) is not True or (body['kind'] == 'answer' and actor != scope['seller_id']):
            raise Rejected('denied')
        if body['kind'] == 'hide' and body['question_id'] not in scope.get('assigned_question_ids', []):
            raise Rejected('denied')
        publish = False
        if body['kind'] in ('ask', 'answer') and self.assessment and not sensitive(text):
            try:
                publish = await asyncio.wait_for(self.assessment(text, body['kind']), 1.2) is True
            except (TimeoutError, OSError):
                publish = False
        scope = await self.access(actor, organization, listing)
        if scope.get(permission) is not True or (body['kind'] == 'answer' and actor != scope['seller_id']) or (body['kind'] == 'hide' and body['question_id'] not in scope.get('assigned_question_ids', [])):
            raise Rejected('denied')
        binding = json.dumps(dict(body, actor_id=actor, organization_id=organization, listing_id=listing), sort_keys=True)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT * FROM l18_receipts WHERE operation=?', (body['operation_id'],)).fetchone()
            if old:
                if old['binding'] != binding:
                    raise Rejected('conflict')
                result = json.loads(old['result'])
            else:
                result = self.apply(actor, listing, body, scope, publish)
                result.update(subject_id=listing, watch_id=body['watch_id'], actor_id=actor, organization_id=organization, expected_revision=body['expected_revision'], source_revision=body['source_revision'], pending_reason='content_review' if result['state'] == 'held' else None, next_actor='moderator' if result['state'] in ('held', 'reported') else None, next_review_at=None)
                self.db.execute('INSERT INTO l18_receipts VALUES (?,?,?)', (body['operation_id'], binding, json.dumps(result)))
                event = {key: result[key] for key in ('schema_version', 'operation_id', 'question_id', 'state', 'revision')}
                self.db.execute('INSERT INTO l18_outbox VALUES (?,?)', (body['operation_id'], json.dumps(event)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def apply(self, actor, listing, body, scope, publish):
        if scope['watch_id'] != body['watch_id'] or scope['revision'] != body['source_revision']:
            raise Rejected('stale')
        kind, key, text = body['kind'], body['question_id'], body['text'].strip()
        row = self.db.execute('SELECT * FROM l18_questions WHERE id=? AND listing=?', (key, listing)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if kind == 'ask':
            if self.db.execute('SELECT 1 FROM l18_questions WHERE id=? AND listing<>?', (key, listing)).fetchone():
                raise Rejected('conflict')
            if row or body['expected_revision'] != 0:
                raise Rejected('stale')
            state = 'held' if not publish else 'published'
            self.db.execute('INSERT INTO l18_questions VALUES (?,?,?,?,?,?,?,NULL,?,1)', (key, listing, body['watch_id'], actor, scope['seller_id'], text, normalized(text), state))
            revision = 1
        else:
            if not row or row['watch'] != scope['watch_id'] or row['revision'] != body['expected_revision']:
                raise Rejected('stale')
            revision, state = row['revision'] + 1, row['state']
            if kind == 'answer':
                if actor != scope['seller_id'] or actor != row['seller'] or scope.get('can_answer') is not True:
                    raise Rejected('denied')
                if row['state'] != 'published':
                    raise Rejected('denied')
                state = 'held' if not publish else 'published'
                self.db.execute('UPDATE l18_questions SET answer=?,state=?,revision=? WHERE id=?', (text, state, revision, key))
            elif kind == 'report':
                self.db.execute('INSERT INTO l18_reports VALUES (?,?,?,?,?)', (body['operation_id'], key, actor, text, now))
                state = 'reported'
            elif kind == 'appeal':
                if actor not in (row['author'], row['seller']) or row['state'] == 'published':
                    raise Rejected('denied')
                self.db.execute('INSERT INTO l18_appeals VALUES (?,?,?,?,?)', (body['operation_id'], key, actor, text, now))
            else:
                reported = self.db.execute('SELECT 1 FROM l18_reports WHERE question=? AND reporter=? LIMIT 1', (key, actor)).fetchone()
                if scope.get('assigned_moderator') is not True or actor in (row['author'], row['seller']) or reported:
                    raise Rejected('denied')
                self.db.execute('INSERT INTO l18_audit VALUES (?,?,?,?,?)', (body['operation_id'], actor, key, text, now))
                state = 'hidden'
            if kind != 'answer':
                self.db.execute('UPDATE l18_questions SET state=?,revision=? WHERE id=?', (state, revision, key))
        return {'schema_version': 'listing-questions.v1', 'operation_id': body['operation_id'], 'question_id': key, 'state': state, 'revision': revision}
