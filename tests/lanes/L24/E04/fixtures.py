"""Deterministic synthetic inputs; no fixture establishes transaction acceptance."""
from datetime import datetime, timezone

DOMAINS = (
    "identity", "catalog", "auction", "pricing", "orders", "eligibility",
    "trust", "service-operations", "communications",
)
ROLES = (
    "visitor", "buyer", "prospective_seller", "private_seller", "dealer", "brand",
    "colleague", "seller_reviewer", "assessor", "eligibility_reviewer",
    "brand_approver", "authenticator", "quality_reviewer", "moderator", "operator",
    "recovery_operator",
)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
BINDING = {
    "operation_id": "synthetic-operation-1", "subject_id": "synthetic-buyer-1",
    "watch_id": "synthetic-watch-1", "actor_id": "synthetic-reviewer-1",
    "organization_id": "synthetic-business-1", "expected_revision": 2,
    "quote_revision": 3, "policy_revision": 1,
}


def actors():
    return [
        {"role": role, "seller_id": f"synthetic-seller-{seller}",
         "organization_id": f"synthetic-business-{business}", "synthetic": True}
        for role in ROLES for seller in (1, 2) for business in (1, 2)
    ]


def evidence():
    return {
        "file_id": "synthetic-file-1", "binding": dict(BINDING),
        "retention": "reviewed", "retention_start": NOW.isoformat(),
        "active_case": False, "synthetic": True,
    }


def outcomes():
    base = dict(BINDING, schema_version="l24.restore.v1", revision=2,
                pending_reason=None, next_actor=None, next_review_at=None)
    return {
        "success": dict(base, state="complete"),
        "denied": dict(base, state="denied"),
        "stale": dict(base, state="stale", revision=3),
        "lost_response": dict(base, state="pending", pending_reason="lookup_required",
                              next_actor="synthetic-operator", next_review_at=NOW.isoformat()),
        "timeout": dict(base, state="unavailable", pending_reason="lookup_timeout",
                        next_actor="synthetic-operator", next_review_at=NOW.isoformat()),
        "duplicate": dict(base, state="complete"),
    }


def current_case():
    """Current scoped preservation and assignment assertions from a substitute."""
    scope = dict(case_id="synthetic-case-1", case_revision=2, assignment_revision=3,
                 active=True, binding=dict(BINDING))
    return {"active": True, "binding": dict(BINDING),
            "retention_case": dict(scope, file_id="synthetic-file-1", needs_evidence=True),
            "assignment": dict(scope)}
