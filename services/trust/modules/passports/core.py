"""Durable inspection summaries with a provider-owned serialized source guard."""
import base64
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
from typing import Callable, Protocol
from uuid import UUID, uuid4
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_spec = importlib.util.spec_from_file_location('passports_v1', Path(__file__).resolve().parents[4] / 'packages/contracts-trust/passports/v1.py')
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)
Issue, Summary, Signed = _contract.Issue, _contract.Summary, _contract.Signed


class Failure(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Source:
    actor_id: UUID
    subject_id: UUID
    organization_id: UUID
    watch_id: UUID
    inspection_id: UUID
    revision: int
    issuer_id: UUID
    expert_id: UUID
    seller_id: UUID
    inspected_at: datetime
    completed_at: datetime
    assignment_revision: int
    custody_receipt_id: UUID
    commitment_id: UUID
    quote_id: UUID
    quote_revision: int
    policy_revision: int
    result_revision: int
    permitted: bool
    independent: bool
    paid_received: bool
    released_completed: bool
    private_sale: bool
    passed: bool


class Provider(Protocol):
    def guard(self, actor_id: UUID, request: Issue, *, timeout: float) -> AbstractContextManager[Source]:
        """Hold current authority/source bindings through the local commit."""
        ...


def canonical(summary: Summary) -> bytes:
    return b'beirut-time.passports.summary.v1\n' + json.dumps(summary.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def bindings_for(source: Source) -> str:
    return json.dumps({k: str(v) for k, v in vars(source).items() if k != 'permitted'}, sort_keys=True)


class Passports:
    def __init__(self, database: str, provider: Provider, key_id: UUID,
                 signing_key: Ed25519PrivateKey, issuers: dict[UUID, tuple[UUID, Ed25519PublicKey]],
                 clock: Callable[[], datetime]):
        self.database, self.provider, self.key_id = database, provider, key_id
        self.signing_key, self.issuers, self.clock = signing_key, dict(issuers), clock
        with self.connect() as db:
            db.executescript((Path(__file__).parent / 'migrations/L20_0001_passports.sql').read_text())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=1.0)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        except sqlite3.OperationalError:
            raise Failure('unavailable', 503) from None
        finally:
            db.close()

    def authorize(self, actor: UUID, request: Issue, source: Source):
        if not source.permitted or (source.actor_id, source.subject_id, source.organization_id, source.watch_id, source.inspection_id) != (actor, request.subject_id, request.organization_id, request.watch_id, request.inspection_id):
            raise Failure('denied', 403)
        if source.revision != request.expected_revision:
            raise Failure('stale_revision', 409)
        if not all((source.independent, source.expert_id != source.seller_id, source.paid_received,
                    source.released_completed, source.private_sale, source.passed)):
            raise Failure('inspection_required', 409)
        now = self.clock()
        dates = (source.inspected_at, source.completed_at, now)
        if any(d.tzinfo is None or d.utcoffset() != timezone.utc.utcoffset(d) for d in dates):
            raise Failure('unavailable', 503)
        if not source.inspected_at <= source.completed_at <= now:
            raise Failure('inspection_required', 409)
        if any(type(v) is not int or v < 1 for v in (source.revision, source.assignment_revision, source.quote_revision, source.policy_revision, source.result_revision)):
            raise Failure('unavailable', 503)
        return now

    def issue(self, actor: UUID, request: Issue) -> Signed:
        try:
            with self.provider.guard(actor, request, timeout=1.2) as source:
                now = self.authorize(actor, request, source)
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    existing = db.execute('SELECT * FROM l20_passports WHERE operation_id=?', (str(request.operation_id),)).fetchone()
                    encoded = request.model_dump_json()
                    if existing:
                        if existing['actor_id'] != str(actor) or existing['request'] != encoded:
                            raise Failure('operation_conflict', 409)
                        if existing['bindings'] != bindings_for(source):
                            raise Failure('stale_revision', 409)
                        return Signed.model_validate_json(existing['document'])
                    summary = Summary(passport_id=uuid4(), issuer_id=source.issuer_id,
                        inspected_at=source.inspected_at, issued_at=now,
                        scope='independent_private_sale_inspection', watch_reference=uuid4(),
                        inspected_revision=source.revision, claim='historical_inspection_summary_only')
                    document = Signed(summary=summary, key_id=self.key_id,
                        signature=base64.urlsafe_b64encode(self.signing_key.sign(canonical(summary))).decode().rstrip('='))
                    self.verify(document)
                    bindings = bindings_for(source)
                    db.execute('INSERT INTO l20_passports VALUES (?,?,?,?,?,?,?)', (str(request.operation_id), str(actor), encoded, str(request.inspection_id), str(summary.passport_id), bindings, document.model_dump_json()))
                    db.execute('INSERT INTO l20_passport_outbox(event_id,document) VALUES (?,?)', (str(request.operation_id), document.model_dump_json()))
                    return document
        except Failure:
            raise
        except sqlite3.IntegrityError:
            raise Failure('inspection_already_issued', 409) from None
        except (TimeoutError, ConnectionError, sqlite3.OperationalError):
            raise Failure('unavailable', 503) from None

    def lookup(self, actor: UUID, operation_id: UUID) -> Signed:
        with self.connect() as db:
            row = db.execute('SELECT * FROM l20_passports WHERE operation_id=?', (str(operation_id),)).fetchone()
        if row is None or row['actor_id'] != str(actor):
            raise Failure('not_found', 404)
        request = Issue.model_validate_json(row['request'])
        try:
            with self.provider.guard(actor, request, timeout=1.2) as source:
                self.authorize(actor, request, source)
                if row['bindings'] != bindings_for(source):
                    raise Failure('stale_revision', 409)
                return Signed.model_validate_json(row['document'])
        except (TimeoutError, ConnectionError):
            raise Failure('unavailable', 503) from None

    def verify(self, document: Signed) -> Signed:
        trusted = self.issuers.get(document.key_id)
        if trusted is None or trusted[0] != document.summary.issuer_id:
            raise Failure('invalid_signature', 422)
        try:
            trusted[1].verify(base64.urlsafe_b64decode(document.signature + '=='), canonical(document.summary))
        except (InvalidSignature, ValueError):
            raise Failure('invalid_signature', 422) from None
        return document

    def public(self, passport_id: UUID) -> Signed:
        with self.connect() as db:
            row = db.execute('SELECT document FROM l20_passports WHERE passport_id=?', (str(passport_id),)).fetchone()
        if row is None:
            raise Failure('not_found', 404)
        return self.verify(Signed.model_validate_json(row['document']))
