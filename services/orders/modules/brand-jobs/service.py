"""Private authorization coordinator; canonical Orders owns the atomic effect."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3


class Coordinator:
    def __init__(self, path, provider):
        self.provider = provider
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS receipts (operation TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS coordination (operation TEXT PRIMARY KEY, outcome TEXT, recovery TEXT)')
        self.db.commit()

    def close(self):
        self.db.close()

    async def lookup(self, command):
        return await self._resolve(command, create=False)

    @staticmethod
    def digest(command):
        return hashlib.sha256(json.dumps(asdict(command), sort_keys=True).encode()).hexdigest()

    @staticmethod
    def result(command, state, reason=None):
        return dict(schema_version='orders.brand-jobs.v1', **asdict(command), state=state,
                    revision=command.expected_revision, pending_reason=reason,
                    next_actor=None, next_review_at=None)

    async def held(self, command, state, reason):
        await asyncio.wait_for(self.provider.check_access(command), 2)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO receipts VALUES (?,?,NULL)',
                            (command.operation_id, self.digest(command)))
            self.db.execute('INSERT OR IGNORE INTO coordination VALUES (?,NULL,NULL)', (command.operation_id,))
        binding = self.db.execute('SELECT digest FROM receipts WHERE operation=?', (command.operation_id,)).fetchone()
        if binding[0] != self.digest(command):
            raise ValueError('operation_conflict')
        result = self.result(command, state, reason)
        row = self.db.execute('SELECT recovery FROM coordination WHERE operation=?',
                              (command.operation_id,)).fetchone()
        recovery = json.loads(row[0]) if row and row[0] else None
        if recovery is None:
            # Assignment is durable and idempotent at the responsible provider.
            recovery = await asyncio.wait_for(self.provider.assign_recovery(command), 2)
            try:
                if not isinstance(recovery, dict) or any(
                    not isinstance(recovery.get(field), str) or not 1 <= len(recovery[field]) <= 100
                    for field in ('operator_id', 'next_action', 'escalation_actor_id')
                ):
                    raise ValueError('invalid_recovery_assignment')
                opened = datetime.fromisoformat(recovery['opened_at'])
                if opened.tzinfo != timezone.utc:
                    raise ValueError('invalid_recovery_time')
                recovery = {field: recovery[field] for field in
                            ('operator_id', 'next_action', 'escalation_actor_id', 'opened_at')}
                recovery.update(next_review_at=(opened + timedelta(hours=24)).isoformat(),
                                escalate_at=(opened + timedelta(hours=48)).isoformat())
            except (KeyError, TypeError, ValueError, OverflowError):
                return self.result(command, 'unavailable', 'recovery_assignment_unavailable')
            with self.db:
                self.db.execute('UPDATE coordination SET recovery=? WHERE operation=?',
                                (json.dumps(recovery), command.operation_id))
        return result | dict(next_actor=recovery['operator_id'],
                             next_review_at=recovery['next_review_at'], recovery=recovery)

    async def authorize(self, command):
        return await self._resolve(command, create=True)

    async def _resolve(self, command, create):
        try:
            await asyncio.wait_for(self.provider.check_access(command), 2)
        except (TimeoutError, ConnectionError):
            return self.result(command, 'unavailable', 'current_access_unavailable')
        digest = self.digest(command)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO receipts VALUES (?,?,NULL)', (command.operation_id, digest))
            self.db.execute('INSERT OR IGNORE INTO coordination VALUES (?,NULL,NULL)', (command.operation_id,))
        row = self.db.execute('SELECT digest,result FROM receipts WHERE operation=?', (command.operation_id,)).fetchone()
        if row[0] != digest:
            raise ValueError('operation_conflict')
        row = self.db.execute('SELECT outcome FROM coordination WHERE operation=?', (command.operation_id,)).fetchone()
        outcome = json.loads(row[0]) if row[0] else None
        try:
            scope = await asyncio.wait_for(self.provider.current_scope(command), 2)
            reason = validate(command, scope)
            if not reason and outcome is None:
                receipt = await asyncio.wait_for(self.provider.lookup_operation(command), 2)
                if receipt is None and create:
                    receipt = await asyncio.wait_for(self.provider.authorize_once(command, scope), 2)
                if (receipt and receipt.get('state') == 'authorized' and receipt.get('job_id')
                        and receipt.get('assignee_id') and receipt.get('binding') == asdict(command)
                        and receipt.get('source_revision') == scope.source_revision):
                    outcome = self.result(command, 'authorized') | {
                        'job_id': receipt['job_id'], 'assignee_id': receipt['assignee_id'],
                        'permitted_start_state': 'requires_current_start_check'}
                    with self.db:
                        self.db.execute('UPDATE coordination SET outcome=? WHERE operation=? AND outcome IS NULL',
                                        (json.dumps(outcome), command.operation_id))
                else:
                    reason = 'reconcile'
            if reason != 'current_scope_unavailable' and outcome and outcome['assignee_id'] != scope.assignee_id:
                reason = 'assignment_changed'
            if reason:
                state = ('unavailable' if reason == 'current_scope_unavailable' else
                         'stale' if reason == 'revision' else
                         'denied' if reason in ('scope', 'economics') else 'pending')
                result = await self.held(command, state, reason)
            else:
                result = outcome
        except (TimeoutError, ConnectionError):
            try:
                result = await self.held(command, 'pending', 'reconcile')
            except (TimeoutError, ConnectionError):
                result = self.result(command, 'unavailable', 'recovery_assignment_unavailable')
        with self.db:
            self.db.execute('UPDATE receipts SET result=? WHERE operation=?', (json.dumps(result), command.operation_id))
        return result


def validate(command, scope):
    required = (
        'buyer_id', 'watch_id', 'organization_id', 'revision', 'quote_id',
        'quote_revision', 'policy_revision', 'currency', 'total_minor',
        'business_fee_minor', 'accepted', 'authority_current', 'allocation_current',
        'paid_held', 'assignee_qualified', 'assignee_id', 'order_id',
        'approval_current', 'grant_current', 'consent_current', 'assessor_id',
        'approver_id', 'quality_reviewer_id', 'eligibility_reviewer_id', 'source_revision',
    )
    if command.kind == 'repair':
        required += ('service_acceptance_id', 'payment_operation_id', 'payment_revision')
    if any(not hasattr(scope, field) for field in required):
        return 'current_scope_unavailable'
    if (scope.buyer_id, scope.watch_id, scope.organization_id) != (command.subject_id, command.watch_id, command.organization_id):
        return 'scope'
    if (scope.revision, scope.quote_id, scope.quote_revision, scope.policy_revision) != (command.expected_revision, command.quote_id, command.quote_revision, command.policy_revision):
        return 'revision'
    if scope.currency != 'USD' or type(scope.total_minor) is not int or not 0 < scope.total_minor <= 9007199254740991:
        return 'economics'
    if type(scope.business_fee_minor) is not int or scope.business_fee_minor != (scope.total_minor * 5 + 50) // 100:
        return 'economics'
    if not all(value is True for value in (scope.accepted, scope.authority_current, scope.allocation_current, scope.paid_held, scope.assignee_qualified)) or not scope.assignee_id or not scope.order_id:
        return 'prerequisites'
    if command.kind == 'customization':
        if not all(value is True for value in (scope.approval_current, scope.grant_current, scope.consent_current)):
            return 'execution_grant'
        roles = (scope.assessor_id, scope.approver_id, scope.quality_reviewer_id, scope.eligibility_reviewer_id)
        if not all(roles) or len(set(roles)) != 4 or scope.eligibility_reviewer_id == scope.buyer_id:
            return 'independence'
    else:
        if not scope.quality_reviewer_id or scope.quality_reviewer_id == scope.assessor_id:
            return 'independence'
        if (not command.service_acceptance_id
                or (scope.service_acceptance_id, scope.total_minor)
                != (command.service_acceptance_id, command.service_total_minor)
                or not scope.payment_operation_id or type(scope.payment_revision) is not int
                or scope.payment_revision < 1):
            return 'scope'
        if ((command.service_order_id is not None and command.service_order_id != scope.order_id)
                or (command.service_payment_operation_id is not None
                    and command.service_payment_operation_id != scope.payment_operation_id)
                or (command.service_payment_revision is not None
                    and command.service_payment_revision != scope.payment_revision)):
            return 'scope'
    return None
