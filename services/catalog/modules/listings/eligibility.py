"""Fail-closed publication checks; private evidence never enters public facts."""
import hashlib
import json

from pydantic import ValidationError
from bt_contracts.catalog.listings.eligibility import PublicationEligibility
from bt_contracts_core.errors import PublicError
from .dependencies import service_request


def identity_digest(row):
    facts = row["facts"]
    if isinstance(facts, str):
        facts = json.loads(facts)
    identity = {key: facts.get(key) for key in ("brand", "model", "reference", "year", "modified", "modifications")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def require_eligible(value, binding):
    try:
        proof = PublicationEligibility.model_validate(value)
        projected = proof.model_dump(mode="json")
        if any(projected[name] != expected for name, expected in binding.items()):
            raise ValueError("Eligibility scope mismatch")
        if not proof.current or proof.state == "pending" or proof.duplicate_review == "required":
            details = {name: projected[name] for name in (
                "operation_id", "subject_id", "revision", "pending_reason", "next_actor", "next_review_at",
            )}
            raise PublicError("publication_review_pending", "Current listing possession and duplicate-stock review are not confirmed. Retry the same publication.", status=503, details=details)
        if proof.state != "eligible" or proof.duplicate_review != "clear":
            raise PublicError("publication_review_denied", "Resolve the listing possession or duplicate-stock review before publishing.", status=409)
    except (ValidationError, ValueError, TypeError):
        raise PublicError("publication_review_pending", "Current listing possession and duplicate-stock review are not confirmed. Retry the same publication.", status=503) from None


async def check_publication(request, row, operation_id, actor_id):
    binding = {
        "schema_version": "listing-eligibility.v1",
        "operation_id": operation_id,
        "subject_id": str(row["id"]),
        "listing_id": str(row["id"]),
        "watch_id": str(row["physical_watch_id"]),
        "actor_id": str(actor_id),
        "organization_id": str(row["organization_id"]) if row["organization_id"] else None,
        "expected_revision": row["revision"],
        "identity_digest": identity_digest(row),
    }
    value = await service_request(request, "identity", "POST", "/internal/v1/listing-eligibility/validate",
                                  headers={"Idempotency-Key": operation_id}, json=binding)
    require_eligible(value, binding)
