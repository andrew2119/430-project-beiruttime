"""Acknowledged cleanup of private evidence and minimal audit references."""
import json
from policy import cleanup_due, removable, instant, stamp, REASONS
from store import token, integer, parse


class Retention:
    def __init__(self, store, current_facts):
        self.store = store
        self.current_facts = current_facts
        store.db.execute('''CREATE TABLE IF NOT EXISTS retention(
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, body TEXT NOT NULL)''')

    def register(self, ref, actor, subject, organization, kind, created_at):
        scope = self.store._scope(actor, subject, organization)
        token(ref)
        instant(created_at)
        if kind not in ('unsubmitted', 'proof', 'audit'):
            raise ValueError('invalid')
        body = dict(ref=ref, kind=kind, created_at=stamp(created_at), state='pending', source_revision=0)
        def action():
            old = self.store.db.execute('SELECT scope,body FROM retention WHERE id=?', (ref,)).fetchone()
            if old and (old['scope'] != scope or json.loads(old['body'])['kind'] != kind or json.loads(old['body'])['created_at'] != body['created_at']):
                raise ValueError('conflict')
            if not old:
                self.store.db.execute('INSERT INTO retention VALUES(?,?,?)', (ref, scope, json.dumps(body)))
        self.store._atomic(action)

    def _candidate(self, body, subject, organization, now):
        facts = self.current_facts(body['ref'], subject, organization)
        if facts is None:
            return None
        integer(facts['revision'], 1)
        obligations = facts.get('obligations')
        if not isinstance(obligations, list) or any(reason not in REASONS for reason in obligations):
            return None
        if obligations or facts['revision'] < body['source_revision'] or type(facts['active_case']) is not bool:
            return None
        due = cleanup_due(body['kind'], parse(body['created_at']),
                          parse(facts['final_review_at']) if facts['final_review_at'] else None,
                          facts['active_case'])
        if removable(now, due):
            return dict(ref=body['ref'], expected_source_revision=facts['revision'])
        return None

    def scan(self, actor, subject, organization, now, after=''):
        scope = self.store._scope(actor, subject, organization)
        instant(now)
        if after:
            token(after)
        rows = self.store.db.execute("SELECT id,body FROM retention WHERE scope=? AND id>? AND json_extract(body, '$.state') != 'removed' ORDER BY id LIMIT 100", (scope, after)).fetchall()
        candidates = []
        for row in rows:
            candidate = self._candidate(json.loads(row['body']), subject, organization, now)
            if candidate:
                candidates.append(candidate)
        return dict(items=candidates, next_cursor=rows[-1]['id'] if len(rows) == 100 else None)

    def candidates(self, actor, subject, organization, now):
        return self.scan(actor, subject, organization, now)['items']

    def acknowledge(self, ref, actor, subject, organization, source_revision, removed, now):
        scope = self.store._scope(actor, subject, organization)
        integer(source_revision, 1)
        if type(removed) is not bool:
            raise ValueError('invalid')
        def action():
            row = self.store.db.execute('SELECT body FROM retention WHERE id=? AND scope=?', (token(ref), scope)).fetchone()
            if not row:
                raise ValueError('denied')
            body = json.loads(row['body'])
            if body['state'] == 'removed':
                return 'removed'
            candidate = self._candidate(body, subject, organization, now)
            if candidate is None or candidate['expected_source_revision'] != source_revision:
                raise ValueError('stale')
            body.update(state='removed' if removed else 'partial', source_revision=source_revision)
            self.store.db.execute('UPDATE retention SET body=? WHERE id=?', (json.dumps(body), ref))
            return body['state']
        return self.store._atomic(action)
