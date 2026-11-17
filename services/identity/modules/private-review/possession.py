"""Pure listing-possession transitions for a serialized persistence boundary."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from uuid import UUID


class PossessionDenied(ValueError):
    pass


@dataclass(frozen=True)
class ListingFacts:
    seller_id: UUID
    watch_id: UUID
    watch_revision: int
    listing_revision: int
    seller_approved: bool


@dataclass(frozen=True)
class Possession:
    facts: ListingFacts
    revision: int
    state: str
    issued_at: datetime
    code_digest: str
    evidence_ref: UUID | None = None
    reviewer_id: UUID | None = None
    assignment_revision: int = 0
    reason: str | None = None
    submitted_at: datetime | None = None


def digest(challenge_id: UUID, code: str) -> str:
    if len(code) != 6 or not all(char.isdecimal() for char in code):
        raise PossessionDenied("invalid_code")
    normalized = "".join(str(int(char)) for char in code)
    return sha256(f"{challenge_id}:{normalized}".encode()).hexdigest()


def issue(facts, actor_id, challenge_id, code, now, *, existing=None):
    if actor_id != facts.seller_id or not facts.seller_approved:
        raise PossessionDenied("seller_permission_required")
    if now.tzinfo is None:
        raise PossessionDenied("server_time_required")
    if existing is not None and existing.facts == facts:
        expired_challenge = (existing.state == "issued"
                             and now >= existing.issued_at + timedelta(hours=24))
        if existing.state not in {"correction", "rejected"} and not expired_challenge:
            raise PossessionDenied("existing_proof_protected")
    return Possession(facts, existing.revision + 1 if existing else 1, "issued", now,
                      digest(challenge_id, code),
                      assignment_revision=existing.assignment_revision if existing else 0)


def current(proof, facts, revision):
    if proof.facts != facts or proof.revision != revision:
        raise PossessionDenied("stale_revision")
    if not facts.seller_approved:
        raise PossessionDenied("seller_permission_required")


def submit(proof, facts, actor_id, revision, challenge_id, code, evidence_ref, now,
           *, evidence_owned):
    current(proof, facts, revision)
    if actor_id != facts.seller_id or not evidence_owned or evidence_ref is None:
        raise PossessionDenied("private_evidence_required")
    if proof.state != "issued":
        raise PossessionDenied("single_use_code")
    if now < proof.issued_at or now >= proof.issued_at + timedelta(hours=24):
        raise PossessionDenied("proof_expired")
    if not compare_digest(proof.code_digest, digest(challenge_id, code)):
        raise PossessionDenied("invalid_code")
    return replace(proof, revision=proof.revision + 1, state="pending",
                   code_digest="", evidence_ref=evidence_ref, submitted_at=now)


def assign(proof, facts, revision, reviewer_id, *, operator_permitted,
           reviewer_qualified):
    current(proof, facts, revision)
    if not operator_permitted or not reviewer_qualified or reviewer_id == facts.seller_id:
        raise PossessionDenied("independent_assignment_required")
    if proof.state != "pending":
        raise PossessionDenied("pending_review_required")
    return replace(proof, reviewer_id=reviewer_id, revision=proof.revision + 1,
                   assignment_revision=proof.assignment_revision + 1)


def read_evidence(proof, facts, actor_id, *, reviewer_qualified):
    if proof.facts != facts or not reviewer_qualified or actor_id != proof.reviewer_id:
        raise PossessionDenied("current_assignment_required")
    if actor_id == facts.seller_id or proof.evidence_ref is None:
        raise PossessionDenied("independent_assignment_required")
    return proof.evidence_ref


def decide(proof, facts, actor_id, revision, assignment_revision, verdict, reason,
           *, reviewer_qualified):
    current(proof, facts, revision)
    read_evidence(proof, facts, actor_id, reviewer_qualified=reviewer_qualified)
    if assignment_revision != proof.assignment_revision:
        raise PossessionDenied("stale_assignment")
    if proof.state != "pending" and not (proof.state == "approved" and verdict == "suspended"):
        raise PossessionDenied("pending_review_required")
    if verdict not in {"approved", "correction", "rejected", "suspended"}:
        raise PossessionDenied("invalid_verdict")
    if not 5 <= len(reason.strip()) <= 500:
        raise PossessionDenied("reason_required")
    return replace(proof, state=verdict, reason=reason.strip(), revision=proof.revision + 1)


def publication_allowed(proof, facts):
    return bool(proof and proof.facts == facts and facts.seller_approved
                and proof.state == "approved")
