"""Provider calls run within a bounded current-authorization lease."""
import json
import sqlite3
from datetime import timedelta

class Service:
    def __init__(self, store, authority, clock):
        self.store, self.authority, self.clock = store, authority, clock

    def scope(self, subject, organization):
        return str(subject) + ':' + (str(organization) if organization else '-')

    def run(self, actor, subject, organization, action, change=None, operation_id=None):
        value = self._run(actor, subject, organization, action, change, operation_id)
        return self.envelope(value, actor, subject, organization, change, operation_id)

    def envelope(self, value, actor, subject, organization, change=None, operation_id=None):
        pending = value.get('state') == 'pending'
        return {
            'schema_version': 1,
            'operation_id': str(change.operation_id) if change else str(operation_id) if operation_id else None,
            'subject_id': str(subject),
            'watch_id': None,
            'actor_id': actor,
            'organization_id': str(organization) if organization else None,
            'expected_revision': change.expected_revision if change else None,
            'state': 'succeeded',
            'revision': 0,
            'pending_reason': None,
            'next_actor': actor if pending else None,
            'next_review_at': (self.clock() + timedelta(hours=24)).isoformat() if pending else None,
            **value,
        }

    def _run(self, actor, subject, organization, action, change=None, operation_id=None):
        scope = self.scope(subject, organization)
        try:
            # Producer guarantees authority cannot be revoked during this lease.
            with self.authority.lease(actor, subject, organization, timeout_seconds=2) as grant:
                with self.store.transaction():
                    if not grant.allowed:
                        self.store.decision(actor, scope, 'access_denied')
                        return {'state':'denied', 'code':'access_denied'}
                    if action == 'read':
                        self.store.decision(actor, scope, 'read')
                        return self.store.current(scope)
                    op = str(change.operation_id) if change else str(operation_id)
                    old = self.store.db.execute('SELECT scope,actor,request,result FROM operations WHERE id=?', (op,)).fetchone()
                    if old and (old[0] != scope or old[1] != actor):
                        self.store.decision(actor, scope, 'operation_conflict')
                        return {'state':'denied','code':'operation_conflict'}
                    if action == 'lookup':
                        self.store.decision(actor, scope, 'lookup')
                        return json.loads(old[3]) if old else {'state':'pending','pending_reason':'operation_unknown'}
                    if change is None or self.scope(change.subject_id, change.organization_id) != scope:
                        return self.deny(actor, scope, 'scope_mismatch')
                    request = change.model_dump_json()
                    if old:
                        if old[2] != request:
                            return self.deny(actor, scope, 'operation_conflict')
                        self.store.decision(actor, scope, 'duplicate')
                        return json.loads(old[3])
                    proof = grant.verify(change, timeout_seconds=2)
                    now = self.clock()
                    valid = (proof.verified_contact and proof.recipient_verified and
                             proof.second_factor_verified and proof.reauthenticated and
                             proof.actor_id == actor and proof.change == change and
                             proof.issued_at <= now < proof.expires_at and
                             now < proof.issued_at + timedelta(seconds=300))
                    revision = self.store.current(scope)['revision']
                    code = 'stale_revision' if revision != change.expected_revision else 'verification_required' if not valid else None
                    result = {'schema_version':1,'operation_id':op,'subject_id':str(subject),
                              'organization_id':str(organization) if organization else None,
                              'state':'denied' if code else 'succeeded','revision':revision if code else revision+1}
                    result = self.envelope(result, actor, subject, organization, change)
                    if code:
                        result['code'] = code
                    else:
                        result['recipient_version'] = revision+1
                        body = json.dumps({'method':change.method,'reference':change.reference,'synthetic':True})
                        self.store.db.execute('INSERT INTO recipients VALUES(?,?,?)', (scope,revision+1,body))
                        self.store.db.execute('INSERT INTO outbox VALUES(?,?)', (op,json.dumps(result)))
                    self.store.db.execute('INSERT INTO operations VALUES(?,?,?,?,?)', (op,scope,actor,request,json.dumps(result)))
                    self.store.decision(actor, scope, code or 'changed')
                    return result
        except sqlite3.OperationalError as error:
            if (getattr(error, 'sqlite_errorcode', 0) & 255) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            return {'state':'pending','pending_reason':'store_unavailable'}
        except (TimeoutError, ConnectionError):
            return {'state':'pending','pending_reason':'authority_unavailable'}

    def deny(self, actor, scope, code):
        self.store.decision(actor, scope, code)
        return {'state':'denied','code':code}
