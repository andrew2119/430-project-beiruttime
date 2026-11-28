"""Durable local command boundary; provider facts must be freshly resolved."""
import hashlib
import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timedelta, timezone


class Rejected(Exception):
    pass


class Assessment:
    def __init__(self, path, resolve, assign_followup=None):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS l17_records(subject TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l17_receipts(operation TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l17_history(subject TEXT, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l17_outbox(operation TEXT PRIMARY KEY, body TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL DEFAULT '');
        ''')
        self.resolve = resolve
        self.assign_followup = assign_followup

    def authority(self, actor, organization, subject):
        # The resolver must use a bounded current provider read, never a projection.
        facts = self.resolve(actor, organization, subject)
        if not facts:
            raise Rejected('unavailable')
        if not (facts['active'] and facts['technical'] and facts['official_brand']
                and facts['organization_id'] == organization and facts['actor_id'] == actor
                and facts['subject_id'] == subject and facts['brand_id'] == organization
                and actor not in (facts['approver_id'], facts['quality_reviewer_id'])):
            raise Rejected('denied')
        return facts

    def lookup(self, actor, organization, subject, operation):
        facts = self.authority(actor, organization, subject)
        current = self._read(actor, organization, subject, facts)
        row = self.db.execute('SELECT body FROM l17_receipts WHERE operation=?', (operation,)).fetchone()
        if not row:
            return None
        result = json.loads(row[0])
        if (result['actor_id'], result['organization_id'], result['subject_id']) != (actor, organization, subject):
            raise Rejected('denied')
        if current['claimant'] != actor:
            if (current['claimant'] is None and result.get('kind') == 'correct'
                    and result['state'] == 'correction'):
                return self.summary(result)
            raise Rejected('denied')
        return self.recover(result, facts, current)

    def read(self, actor, organization, subject):
        return self._read(actor, organization, subject, self.authority(actor, organization, subject))

    def _read(self, actor, organization, subject, f):
        row = self.db.execute('SELECT body FROM l17_records WHERE subject=?', (subject,)).fetchone()
        if row:
            r = json.loads(row[0])
            if r['organization_id'] != organization or (r['claimant'] is not None and r['claimant'] != actor):
                raise Rejected('denied')
        else:
            r = {'schema_version': 'brand-assessment.v1', 'subject_id': subject, 'organization_id': organization,
                 'watch_id': f['watch_id'], 'revision': 0, 'assignment_revision': 0, 'claimant': None,
                 'state': 'submitted', 'pending_reason': None, 'next_actor': actor, 'next_review_at': None}
        revised = (r.get('request_revision', f['request_revision']) != f['request_revision']
                   or r.get('capability_revision', f['capability_revision']) != f['capability_revision']
                   or r['watch_id'] != f['watch_id'])
        if r['claimant'] is None or revised:
            r = self.summary(r)
        return {**r, 'actor_id': actor, 'state': 'revised' if revised else r['state'],
                'current_watch_id': f['watch_id'],
                'current_request_revision': f['request_revision'],
                'current_scope': {'base_id': f['base_id'], 'caliber_id': f['caliber_id'], 'option_snapshots': f['option_snapshots']},
                'request_revision': r.get('request_revision', f['request_revision']),
                'capability_revision': r.get('capability_revision', f['capability_revision']),
                'current_capability_revision': f['capability_revision']}

    @staticmethod
    def summary(result):
        return {key: value for key, value in result.items() if key in {
            'schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id',
            'expected_revision', 'request_revision', 'assignment_revision', 'capability_revision',
            'revision', 'state', 'claimant', 'pending_reason', 'next_actor', 'next_review_at'}}

    def recover(self, result, facts, current):
        revised = (result['request_revision'] != facts['request_revision']
                   or result['capability_revision'] != facts['capability_revision']
                   or result['watch_id'] != facts['watch_id']
                   or result['assignment_revision'] != current['assignment_revision'])
        if revised:
            return {**self.summary(result), 'state': 'revised',
                    'current_request_revision': facts['request_revision'],
                    'current_capability_revision': facts['capability_revision']}
        return result

    def command(self, c):
        c = c.model_dump()
        f = self.authority(c['actor_id'], c['organization_id'], c['subject_id'])
        digest = hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT digest,body FROM l17_receipts WHERE operation=?', (c['operation_id'],)).fetchone()
            if old:
                if old[0] != digest:
                    raise Rejected('operation_conflict')
                record = self.db.execute('SELECT body FROM l17_records WHERE subject=?', (c['subject_id'],)).fetchone()
                current = json.loads(record[0]) if record else None
                owns = current and current['organization_id'] == c['organization_id'] and current['claimant'] == c['actor_id']
                if not owns and c['kind'] not in ('release', 'correct', 'reassign'):
                    raise Rejected('denied')
                self.db.execute('COMMIT')
                return self.recover(json.loads(old[1]), f, current) if owns else self.summary(json.loads(old[1]))
            row = self.db.execute('SELECT body FROM l17_records WHERE subject=?', (c['subject_id'],)).fetchone()
            r = json.loads(row[0]) if row else {'revision': 0, 'assignment_revision': 0, 'claimant': None, 'state': 'submitted'}
            if (f['request_revision'] != c['request_revision'] or f['watch_id'] != c['watch_id']
                    or f['capability_revision'] != c['capability_revision']
                    or r['revision'] != c['expected_revision']
                    or r['assignment_revision'] != c['assignment_revision']):
                raise Rejected('stale')
            if row and r['organization_id'] != c['organization_id']:
                raise Rejected('denied')
            snapshots = f['option_snapshots']
            if (f['request_state'] != 'submitted' or len(snapshots) != 5
                    or {item['dimension'] for item in snapshots} != {'color_finish', 'material_grade', 'movement', 'dial_hands_markers', 'finishing_package'}
                    or any(not item['option_id'] or type(item['option_revision']) is not int or item['option_revision'] < 1 for item in snapshots)):
                raise Rejected('request_not_current')
            kind = c['kind']
            revised = row and (r['request_revision'] != f['request_revision'] or r['capability_revision'] != f['capability_revision'] or r['watch_id'] != f['watch_id'])
            if revised and kind != 'claim':
                raise Rejected('stale')
            if r['state'] == 'correction_pending':
                raise Rejected('pending')
            if kind == 'claim':
                if r['claimant'] is not None and not (revised and r['claimant'] == c['actor_id']):
                    raise Rejected('claimed')
                r['claimant'] = c['actor_id']
                r['assignment_revision'] += 1
                r['state'] = 'claimed'
            else:
                if r['claimant'] != c['actor_id']:
                    raise Rejected('denied')
                if kind in ('release', 'reassign'):
                    target = c['replacement_id'] if kind == 'reassign' else None
                    if kind == 'reassign':
                        if not target or target == c['actor_id']:
                            raise Rejected('replacement_required')
                        self.authority(target, c['organization_id'], c['subject_id'])
                    r['claimant'] = target
                    r['assignment_revision'] += 1
                    r['state'] = 'claimed' if target else 'submitted'
                elif kind == 'assess':
                    if not c['feasibility'] or not c['limitations'].strip() or not c['lead_time_basis'].strip():
                        raise Rejected('assessment_required')
                    if any(not p.strip() or len(p) > 300 for p in c['parts']):
                        raise Rejected('parts_invalid')
                    r['state'] = 'assessed'
                    r['assessment_id'] = str(uuid4())
                    r['assessment_revision'] = 1
                    r['assessor_id'] = c['actor_id']
                else:
                    if not c['reason'].strip():
                        raise Rejected('reason_required')
                    r['state'] = 'correction_pending'
                    self.db.execute('INSERT INTO l17_outbox(operation,body) VALUES(?,?)', (c['operation_id'], json.dumps(c)))
            if kind != 'assess':
                for key in ('assessment_id', 'assessment_revision', 'assessor_id'):
                    r.pop(key, None)
            if kind != 'correct':
                for key in ('responsible_operator_id', 'next_action', 'escalation_at'):
                    r.pop(key, None)
            now = datetime.now(timezone.utc)
            r.update({**c, 'option_snapshots': snapshots, 'base_id': f['base_id'], 'caliber_id': f['caliber_id'], 'revision': r['revision'] + 1, 'assignment_revision': r['assignment_revision'],
                      'state': r['state'], 'pending_reason': 'catalog_receipt' if kind == 'correct' else None,
                      'next_actor': 'catalog' if kind == 'correct' else c['actor_id'],
                      'next_review_at': (now + timedelta(hours=24)).isoformat() if kind == 'correct' else None})
            if kind == 'correct':
                try:
                    owner = self.assign_followup(c['organization_id'], c['subject_id'], c['operation_id']) if self.assign_followup else None
                except (TimeoutError, ConnectionError):
                    raise Rejected('unavailable') from None
                if not isinstance(owner, str) or not owner.strip() or len(owner) > 100:
                    raise Rejected('unavailable')
                r.update(responsible_operator_id=owner,
                         next_action='recover_catalog_receipt' if owner else 'assignment_unavailable',
                         escalation_at=(now + timedelta(hours=48)).isoformat())
            body = json.dumps(r)
            self.db.execute('INSERT OR REPLACE INTO l17_records VALUES(?,?)', (c['subject_id'], body))
            self.db.execute('INSERT INTO l17_history VALUES(?,?)', (c['subject_id'], body))
            self.db.execute('INSERT INTO l17_receipts VALUES(?,?,?)', (c['operation_id'], digest, body))
            self.db.execute('COMMIT')
            return r
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def catalog_receipt(self, operation, subject, old_revision, new_revision):
        """Called only by the authenticated Catalog adapter after its durable receipt."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            item = self.db.execute('SELECT body,delivered FROM l17_outbox WHERE operation=?', (operation,)).fetchone()
            if not item:
                raise Rejected('unknown_operation')
            c = json.loads(item[0])
            if c['subject_id'] != subject or c['request_revision'] != old_revision or new_revision != old_revision + 1:
                raise Rejected('receipt_conflict')
            if not item[1]:
                r = json.loads(self.db.execute('SELECT body FROM l17_records WHERE subject=?', (subject,)).fetchone()[0])
                for key in ('assessment_id', 'assessment_revision', 'assessor_id'):
                    r.pop(key, None)
                for key in ('responsible_operator_id', 'next_action', 'escalation_at'):
                    r.pop(key, None)
                r.update(state='correction', pending_reason=None, request_revision=new_revision,
                         claimant=None, assignment_revision=r['assignment_revision'] + 1,
                         revision=r['revision'] + 1, next_actor='buyer', next_review_at=None)
                body = json.dumps(r)
                self.db.execute('UPDATE l17_records SET body=? WHERE subject=?', (body, subject))
                self.db.execute('UPDATE l17_receipts SET body=? WHERE operation=?', (body, operation))
                self.db.execute('INSERT INTO l17_history VALUES(?,?)', (subject, body))
                self.db.execute('UPDATE l17_outbox SET delivered=1 WHERE operation=?', (operation,))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
