"""Additive inspection domain and durable local adapter; host composition is separate."""
import asyncio
import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

_contract_path = Path(__file__).resolve().parents[4] / 'packages/contracts-trust/private-inspection/v1.py'
_spec = importlib.util.spec_from_file_location('bt_private_inspection_v1', _contract_path)
contract = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = contract
_spec.loader.exec_module(contract)
Submit, Source, Collection = contract.Submit, contract.Source, contract.Collection
NAMESPACE = UUID('b3df46d4-f623-4bd6-8d2b-d27465ac17da')


class Refusal(Exception):
    def __init__(self, code, status):
        self.code, self.status = code, status
        super().__init__(code)


class Inspection:
    def __init__(self, database, provider, clock):
        self.provider, self.clock = provider, clock
        self.db = sqlite3.connect(database, timeout=1, isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript((Path(__file__).parent / 'migrations/L18_0001_private_inspection.sql').read_text())
        self.lock = asyncio.Lock()

    def close(self):
        self.db.close()

    async def source(self, actor, organization, subject):
        try:
            async with asyncio.timeout(1.2):
                raw = await self.provider.current(actor, organization, subject)
            source = Source.model_validate(raw)
            contract.utc(source.received_at)
            if not contract.fresh(source.checked_at, source.valid_until, self.clock()):
                raise ValueError('expired')
            if (str(source.actor_id), str(source.organization_id), str(source.subject_id)) != (
                str(actor), str(organization), str(subject)
            ) or not source.authorized:
                raise Refusal('denied', 403)
            return source
        except Refusal:
            raise
        except (TimeoutError, ValueError, TypeError, OSError):
            raise Refusal('unavailable', 503) from None

    @staticmethod
    def eligible(source):
        if source.seller_kind != 'private':
            raise Refusal('business_assurance_route', 409)
        if (not source.expert_independent or source.actor_id != source.expert_id
                or source.expert_id in (source.seller_id, source.buyer_id)):
            raise Refusal('independence_required', 403)
        if (source.payment_state != 'paid_held' or not source.commitment_current
                or not source.custody_current or source.incident_open
                or source.custody_to_actor != source.expert_id
                or source.authorized_recipient != source.expert_id
                or source.custody_watch_revision != source.watch_revision):
            raise Refusal('prerequisites_required', 409)
        if contract.utc(source.received_at) > contract.utc(source.checked_at):
            raise Refusal('prerequisites_required', 409)
        commission = (source.price_minor * 5 + 50) // 100
        buyer_fee = (source.price_minor * 3 + 50) // 100
        if (commission != source.seller_commission_minor or buyer_fee != source.buyer_fee_minor
                or not source.return_line_accepted
                or commission + source.return_trip_minor > 9007199254740991):
            raise Refusal('retained_economics_required', 409)

    def saved(self, subject):
        row = self.db.execute('SELECT body FROM l18_results WHERE subject=?', (str(subject),)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def matches(body, source):
        return all(body[key] == str(getattr(source, key)) if isinstance(getattr(source, key), UUID)
                   else body[key] == getattr(source, key)
                   for key in contract.Binding.model_fields) and body['custody_receipt_id'] == str(source.custody_receipt_id)

    @staticmethod
    def same_source(body, source):
        historic = dict(body['source'])
        actual = source.model_dump(mode='json')
        for key in ('checked_at', 'valid_until'):
            historic.pop(key)
            actual.pop(key)
        return historic == actual

    async def submit(self, actor, organization, raw):
        if len(json.dumps(raw, ensure_ascii=False).encode()) > 16384:
            raise Refusal('request_limit', 413)
        try:
            command = Submit.model_validate(raw)
        except ValueError:
            raise Refusal('invalid_request', 422) from None
        if (str(command.actor_id), str(command.organization_id)) != (str(actor), str(organization)):
            raise Refusal('denied', 403)
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        async with self.lock:
            source = await self.source(actor, organization, command.subject_id)
            self.eligible(source)
            row = self.db.execute('SELECT actor,organization,digest,body FROM l18_operations WHERE operation=?',
                                  (str(command.operation_id),)).fetchone()
            if row:
                if row[:3] != (str(actor), str(organization), digest):
                    raise Refusal('operation_conflict', 409)
                return json.loads(row[3])
            body = command.model_dump(mode='json')
            if not self.matches(body, source) or command.checklist_revision != source.checklist_revision:
                raise Refusal('stale_revision', 409)
            if (len(set(command.evidence_refs)) != len(command.evidence_refs)
                    or not set(command.evidence_refs).issubset(source.evidence_refs)):
                raise Refusal('evidence_denied', 403)
            checks = {item.item: item.verdict for item in command.checklist}
            verdicts = set(checks.values())
            derived = 'failed' if 'failed' in verdicts else 'inconclusive' if 'inconclusive' in verdicts else 'passed'
            if len(checks) != 4 or command.result != derived or not command.reason.strip():
                raise Refusal('checklist_required', 422)
            self.db.execute('BEGIN IMMEDIATE')
            try:
                prior = self.db.execute('SELECT actor,organization,digest,body FROM l18_operations WHERE operation=?',
                                        (str(command.operation_id),)).fetchone()
                if prior:
                    if prior[:3] != (str(actor), str(organization), digest):
                        raise Refusal('operation_conflict', 409)
                    self.db.execute('COMMIT')
                    return json.loads(prior[3])
                previous = self.saved(command.subject_id)
                revision = previous['revision'] if previous else 0
                if command.expected_revision != revision:
                    raise Refusal('stale_revision', 409)
                if previous and previous['state'] == 'failed':
                    raise Refusal('operational_decision_required', 409)
                now = contract.utc(self.clock())
                if not contract.fresh(source.checked_at, source.valid_until, now):
                    raise Refusal('unavailable', 503)
                body.update(state=command.result, revision=revision + 1, result_revision=revision + 1,
                            recorded_at=now.isoformat(), pending_reason=None, next_actor=None, next_review_at=None)
                body['source'] = source.model_dump(mode='json')
                self.db.execute('INSERT INTO l18_results VALUES(?,?,?) ON CONFLICT(subject) DO UPDATE SET '
                                'revision=excluded.revision,body=excluded.body',
                                (str(command.subject_id), revision + 1, json.dumps(body)))
                self.db.execute('INSERT INTO l18_history VALUES(?,?,?)',
                                (str(command.subject_id), revision + 1, json.dumps(body)))
                receipt = self.receipt(body)
                self.db.execute('INSERT INTO l18_operations VALUES(?,?,?,?,?,?)',
                                (str(command.operation_id), str(actor), str(organization), str(command.subject_id),
                                 digest, json.dumps(receipt)))
                kinds = ['trust.private-inspection-current.v1']
                if command.result == 'failed':
                    kinds += ['trust.seller-charge-required.v1', 'trust.buyer-watch-price-refund-ready.v1']
                for kind in kinds:
                    event = str(uuid5(NAMESPACE, str(command.operation_id) + kind))
                    fact = {key: receipt[key] for key in ('schema_version', 'operation_id', 'subject_id', 'watch_id',
                                                        'state', 'revision')}
                    self.db.execute('INSERT INTO l18_outbox VALUES(?,?,?)', (event, kind, json.dumps(fact)))
                self.db.execute('COMMIT')
                return receipt
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    @staticmethod
    def receipt(body):
        keys = ('schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id',
                'expected_revision', 'state', 'revision', 'result_revision', 'pending_reason', 'next_actor',
                'next_review_at', 'recorded_at')
        receipt = {key: body[key] for key in keys}
        receipt.update({key: body[key] for key in contract.Binding.model_fields})
        receipt.update({key: body[key] for key in ('custody_receipt_id', 'checklist_revision')})
        receipt.update({key: body['source'][key] for key in ('payment_operation_id', 'payment_revision', 'proof_revision')})
        return contract.Receipt.model_validate(receipt).model_dump(mode='json')

    async def workspace(self, actor, organization, subject):
        source = await self.source(actor, organization, subject)
        self.eligible(source)
        body = self.saved(subject)
        return {**{key: source.model_dump(mode='json')[key] for key in contract.Binding.model_fields},
                'schema_version': 'private-inspection.v1',
                'expected_revision': body['revision'] if body else 0,
                'current_state': body['state'] if body and self.same_source(body, source) else None,
                'custody_receipt_id': str(source.custody_receipt_id),
                'checklist_revision': source.checklist_revision,
                'evidence_refs': [str(ref) for ref in source.evidence_refs]}

    async def lookup(self, actor, organization, subject, operation):
        await self.source(actor, organization, subject)
        row = self.db.execute('SELECT body FROM l18_operations WHERE operation=? AND actor=? '
                              'AND organization=? AND subject=?',
                              (str(operation), str(actor), str(organization), str(subject))).fetchone()
        if not row:
            raise Refusal('not_found', 404)
        return json.loads(row[0])

    async def current(self, actor, organization, subject):
        source = await self.source(actor, organization, subject)
        self.eligible(source)
        body = self.saved(subject)
        if not body:
            raise Refusal('not_found', 404)
        if not self.same_source(body, source):
            raise Refusal('stale_revision', 409)
        failed = body['state'] == 'failed'
        charge_id = str(uuid5(NAMESPACE, str(subject) + ':failure-charge'))
        facts = {**self.receipt(body), 'inspection_prerequisite_passed': body['state'] == 'passed',
                'buyer_handover_blocked': body['state'] != 'passed',
                'seller_payout_blocked': body['state'] != 'passed',
                'seller_charge_required': failed, 'buyer_watch_price_refund_ready': failed,
                'refundable_watch_price_minor': source.price_minor if failed else 0,
                'refundable_fee_minor': 0, 'currency': 'USD',
                'charge_operation_id': charge_id if failed else None,
                'charge_amount_minor': source.seller_commission_minor + source.return_trip_minor if failed else 0,
                'private_publication_restricted': failed, 'return_blocked': True,
                'next_actor': 'support' if body['state'] != 'passed' else None,
                'next_review_at': (contract.utc(datetime.fromisoformat(body['recorded_at']))
                                   + timedelta(hours=24)).isoformat() if body['state'] != 'passed' else None}

        return contract.CurrentResult.model_validate(facts).model_dump(mode='json')

    async def return_readiness(self, actor, organization, subject):
        facts = await self.current(actor, organization, subject)
        if not facts['seller_charge_required']:
            raise Refusal('failed_result_required', 409)
        source = await self.source(actor, organization, subject)
        try:
            async with asyncio.timeout(1.2):
                raw = await self.provider.collection(facts['charge_operation_id'])
            collection = Collection.model_validate(raw)
            if not contract.fresh(collection.checked_at, collection.valid_until, self.clock()):
                raise ValueError('expired')
        except (TimeoutError, ValueError, TypeError, OSError):
            current = await self.current(actor, organization, subject)
            if current['revision'] != facts['revision']:
                raise Refusal('stale_revision', 409)
            return {**current, 'pending_reason': 'collection_unavailable'}
        if (str(collection.operation_id) != facts['charge_operation_id']
                or collection.subject_id != source.subject_id or collection.seller_id != source.seller_id
                or collection.method_id != source.saved_simulated_method_id
                or collection.amount_minor != facts['charge_amount_minor']
                or collection.watch_id != source.watch_id or collection.watch_revision != source.watch_revision
                or collection.source_revision != source.source_revision
                or collection.result_revision != facts['revision']
                or collection.assignment_revision != source.assignment_revision
                or collection.custody_receipt_id != source.custody_receipt_id):
            raise Refusal('collection_binding_mismatch', 409)
        # Revalidate after the bounded collection read; current facts are the authority.
        current = await self.current(actor, organization, subject)
        if not contract.fresh(collection.checked_at, collection.valid_until, self.clock()):
            return {**current, 'pending_reason': 'collection_unavailable'}
        if current['revision'] != facts['revision']:
            raise Refusal('stale_revision', 409)
        ready = collection.state == 'confirmed' and collection.custody_instruction_id is not None
        return {**current, 'return_blocked': not ready, 'private_publication_restricted': not ready,
                'pending_reason': None if ready else 'collection_or_custody_pending'}
