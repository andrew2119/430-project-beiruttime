"""Durable private workflow; Orders remains the only execution authority."""
import asyncio
from dataclasses import asdict
from datetime import timedelta
import json
import sqlite3
from pathlib import Path
import importlib.util

_contract = Path(__file__).resolve().parents[4] / 'packages/contracts-catalog/job-changes/v1.py'
_spec = importlib.util.spec_from_file_location('job_changes_v1', _contract)
# Runtime composition supplies the installed contract package; direct loading also
# supports isolated module checks without changing shared registration.
import sys
contract = sys.modules.get(_spec.name)
if contract is None:
    contract = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = contract
    _spec.loader.exec_module(contract)
Change, Approval, Rejected = contract.Change, contract.Approval, contract.Rejected


class Workflow:
    def __init__(self, database, provider, clock):
        self.db = sqlite3.connect(database, isolation_level=None)
        self.db.execute('PRAGMA busy_timeout=3000')
        self.db.executescript((Path(__file__).parent / 'migrations/L15_0002_job_changes.sql').read_text())
        self.provider, self.clock = provider, clock

    async def call(self, method, *args):
        return await asyncio.wait_for(getattr(self.provider, method)(*args, timeout_seconds=3), 3)

    async def authorize(self, change, actor, organization):
        if actor != change.actor_id or organization != change.organization_id:
            raise Rejected('denied')
        if await self.call('authorized', change, actor, organization) is not True:
            raise Rejected('denied')

    def load(self, operation_id):
        row = self.db.execute('SELECT intent,result,approval FROM l15_changes WHERE id=?', (operation_id,)).fetchone()
        if not row:
            raise Rejected('not_found')
        return Change(**json.loads(row[0])), json.loads(row[1]), json.loads(row[2]) if row[2] else None

    def save(self, change, result, approval=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT result,approval FROM l15_changes WHERE id=?', (change.operation_id,)).fetchone()
            if not old:
                raise Rejected('not_found')
            current = json.loads(old[0])
            if current['revision'] != result['revision'] - 1:
                retained = json.loads(old[1]) if old[1] else None
                states = ['pending_hold', 'awaiting_reapproval', 'pending_resume', 'reapproved']
                if retained == approval and states.index(current['state']) >= states.index(result['state']):
                    self.db.execute('COMMIT')
                    return current
                raise Rejected('stale_revision')
            self.db.execute('UPDATE l15_changes SET result=?,approval=?,active=? WHERE id=?',
                            (json.dumps(result), json.dumps(approval) if approval else None,
                             int(result['state'] != 'reapproved'), change.operation_id))
            # Only minimal private routing references; no scope text or evidence.
            event = {k: result[k] for k in ('schema_version', 'operation_id', 'subject_id', 'revision', 'state')}
            self.db.execute('INSERT INTO l15_change_outbox VALUES (?,?)',
                            (f"{change.operation_id}:{result['revision']}", json.dumps(event)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    async def start(self, change, actor, organization):
        await self.authorize(change, actor, organization)
        row = self.db.execute('SELECT intent FROM l15_changes WHERE id=?', (change.operation_id,)).fetchone()
        if row:
            if json.loads(row[0]) != asdict(change):
                raise Rejected('conflict')
            return await self.lookup(change.operation_id, actor, organization)
        if await self.call('current', change, None) is not True:
            raise Rejected('stale_revision')
        now = contract.instant(self.clock())
        result = {k: v for k, v in asdict(change).items() if k in (
            'schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id',
            'organization_id', 'responsible_operator_id', 'expected_revision')}
        result.update(state='pending_hold', revision=1, pending_reason='orders_hold',
                      active_scope_id=change.source_scope_id,
                      invalidated=['quote', 'eligibility', 'brand_decision', 'buyer_acceptance'],
                      next_actor=change.responsible_operator_id, next_review_at=(now + timedelta(hours=24)).isoformat(),
                      escalation_at=(now + timedelta(hours=48)).isoformat(),
                      execution_authority=False)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT INTO l15_changes(id,subject_id,intent,result) VALUES (?,?,?,?)',
                            (change.operation_id, change.subject_id, json.dumps(asdict(change)), json.dumps(result)))
            event = {k: result[k] for k in ('schema_version', 'operation_id', 'subject_id', 'revision', 'state')}
            self.db.execute('INSERT INTO l15_change_outbox VALUES (?,?)',
                            (f'{change.operation_id}:1', json.dumps(event)))
            self.db.execute('COMMIT')
        except sqlite3.IntegrityError:
            self.db.execute('ROLLBACK')
            existing = self.db.execute('SELECT intent FROM l15_changes WHERE id=?', (change.operation_id,)).fetchone()
            if existing and json.loads(existing[0]) == asdict(change):
                return await self.lookup(change.operation_id, actor, organization)
            raise Rejected('change_exists') from None
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return await self.resume(change.operation_id, actor, organization)

    async def lookup(self, operation_id, actor, organization):
        change, result, _ = self.load(operation_id)
        await self.authorize(change, actor, organization)
        return result

    def matches(self, receipt, change, state):
        return isinstance(receipt, dict) and receipt.get('state') == state and all(
            receipt.get(k) == asdict(change)[k] for k in (
                'operation_id', 'order_id', 'subject_id', 'watch_id', 'organization_id', 'expected_revision',
                'actor_id', 'source_scope_id', 'proposed_scope_id', 'retained_quote_id',
                'retained_quote_revision', 'responsible_operator_id'))

    async def resume(self, operation_id, actor, organization):
        change, result, approval = self.load(operation_id)
        await self.authorize(change, actor, organization)
        if result['state'] not in ('pending_hold', 'pending_resume'):
            return result
        proof = Approval(**approval) if approval else None
        try:
            if await self.call('current', change, proof) is not True:
                if proof is None or not hasattr(self.provider, 'reconcile'):
                    return result
                # A terminal fence prevents a delayed old acceptance from applying.
                receipt = await self.call('reconcile', change, proof, result['revision'])
                if (not self.matches(receipt, change, 'not_applied')
                        or receipt.get('approval') != approval
                        or receipt.get('operation_revision') != result['revision']):
                    return result
                await self.authorize(change, actor, organization)
                result.update(state='awaiting_reapproval', revision=result['revision'] + 1,
                              pending_reason=None)
                return self.save(change, result)
            receipt = await self.call('hold' if proof is None else 'resume', *([change] if proof is None else [change, proof]))
            if not self.matches(receipt, change, 'held' if proof is None else 'reapproved'):
                return result
            if proof and receipt.get('approval') != approval:
                return result
            await self.authorize(change, actor, organization)
            if await self.call('current', change, proof) is not True:
                return result
        except (TimeoutError, ConnectionError):
            return result
        result.update(active_scope_id=change.proposed_scope_id,
                      state='awaiting_reapproval' if proof is None else 'reapproved',
                      revision=result['revision'] + 1, pending_reason=None)
        return self.save(change, result, approval)

    async def accept(self, operation_id, approval, actor, organization):
        change, result, retained = self.load(operation_id)
        await self.authorize(change, actor, organization)
        if retained:
            supplied = asdict(approval)
            supplied['accepted_at'] = retained['accepted_at']
            if retained != supplied:
                raise Rejected('conflict')
            return await self.resume(operation_id, actor, organization)
        if result['state'] != 'awaiting_reapproval':
            raise Rejected('hold_required')
        if (approval.operation_id != operation_id or approval.scope_id != change.proposed_scope_id
                or approval.scope_revision <= change.expected_revision
                or change.actor_id in (approval.approver_id, approval.eligibility_reviewer_id)
                or contract.instant(approval.accepted_at) > contract.instant(self.clock())):
            raise Rejected('stale_scope')
        if await self.call('current', change, approval) is not True:
            raise Rejected('stale_prerequisites')
        result.update(state='pending_resume', revision=result['revision'] + 1, pending_reason='orders_resume')
        self.save(change, result, asdict(approval))
        return await self.resume(operation_id, actor, organization)
