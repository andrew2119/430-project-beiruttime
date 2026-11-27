"""Bounded authority adapters; absent providers stay unavailable, never eligible."""

from datetime import datetime, timezone
from uuid import UUID
from bt_contracts_core.errors import PublicError, AccessDenied
from service_app.catalog_dependencies import service_request


def unavailable():
    raise PublicError(
        "approval_unavailable",
        "Current approval prerequisites cannot be confirmed.",
        status=503,
    )


def check_scope(value, row, *, kind):
    if not isinstance(value, dict):
        unavailable()
    try:
        if not isinstance(value.get("id"), str):
            unavailable()
        UUID(value["id"])
        if (
            type(value.get("revision")) is not int
            or value["revision"] < 1
            or type(value.get("request_revision")) is not int
        ):
            unavailable()
    except (ValueError, KeyError, TypeError):
        unavailable()
    if (
        value.get("request_id") != str(row["id"])
        or value.get("request_revision") != row["revision"]
        or value.get("brand_id") != str(row["brand_id"])
    ):
        raise PublicError(
            "stale_scope",
            f"The current {kind} does not match this request.",
            status=409,
        )
    return value


async def current(request, row, intent=None):
    """Pricing uses frozen pricing-current/v2; other adapters await their freeze.

    Readiness discovers the exact quote through its scoped grant, never a raw-ID
    form or a stale dashboard flag. Commands additionally compare the retained IDs.
    """
    request_id = str(row["id"])
    grant = check_scope(
        await service_request(
            request,
            "eligibility",
            "GET",
            f"/internal/v1/grants/requests/{request_id}",
            params={"purpose": "brand_approval"},
        ),
        row,
        kind="grant",
    )
    quote_id = intent["quote_id"] if intent else grant.get("quote_id")
    try:
        if not isinstance(quote_id, str):
            unavailable()
        quote_id = str(UUID(quote_id))
    except (ValueError, TypeError):
        unavailable()
    raw_quote = await service_request(
        request,
        "pricing",
        "GET",
        f"/internal/v2/quotes/{quote_id}/validation",
        params={"buyer_id": str(row["buyer_id"])},
    )
    if (
        not isinstance(raw_quote, dict)
        or raw_quote.get("schedule_id") != "sample-v1"
        or type(raw_quote.get("policy_revision")) is not int
        or raw_quote.get("policy_revision") != 1
        or raw_quote.get("rounding") != "half_up"
    ):
        unavailable()
    if (
        raw_quote.get("kind") != "brand"
        or raw_quote.get("status") != "valid"
        or not raw_quote.get("accepted_at")
    ):
        raise PublicError(
            "quote_required",
            "A current buyer-accepted brand quote is required.",
            status=409,
        )
    try:
        accepted_at = datetime.fromisoformat(
            raw_quote["accepted_at"].replace("Z", "+00:00")
        )
        if accepted_at.tzinfo is None or accepted_at > datetime.now(timezone.utc):
            unavailable()
    except (ValueError, KeyError, TypeError, AttributeError):
        unavailable()
    quote = check_scope(
        {
            **raw_quote,
            "id": raw_quote.get("quote_id"),
            "revision": raw_quote.get("quote_revision"),
            "request_id": raw_quote.get("source_id"),
            "request_revision": raw_quote.get("source_revision"),
            "brand_id": raw_quote.get("organization_id"),
            "status": "accepted",
        },
        row,
        kind="quote",
    )
    assessment_id = intent["assessment_id"] if intent else quote.get("assessment_id")
    try:
        if not isinstance(assessment_id, str):
            unavailable()
        assessment_id = str(UUID(assessment_id))
    except (ValueError, TypeError):
        unavailable()
    raw_assessment = await service_request(
        request,
        "service-operations",
        "GET",
        f"/internal/v1/brand-assessments/{assessment_id}/current",
    )
    if not isinstance(raw_assessment, dict):
        unavailable()
    assessment = check_scope(
        {**raw_assessment, "brand_id": raw_assessment.get("organization_id")},
        row,
        kind="assessment",
    )
    return {"assessment": assessment, "quote": quote, "grant": grant}


def bind(values, row, intent, approver_id):
    assessment, quote, grant = (values[k] for k in ("assessment", "quote", "grant"))
    for kind, value in values.items():
        if (
            value.get("id") != intent[kind + "_id"]
            or value.get("revision") != intent[kind + "_revision"]
        ):
            raise PublicError(
                "stale_scope", "Review the current approval scope.", status=409
            )
    if (
        assessment.get("status") != "feasible"
        or assessment.get("current") is not True
        or assessment.get("qualified") is not True
    ):
        raise PublicError(
            "assessment_required",
            "A current feasible brand assessment is required.",
            status=409,
        )
    if (
        quote.get("status") != "accepted"
        or quote.get("buyer_id") != str(row["buyer_id"])
        or quote.get("assessment_id") != assessment["id"]
        or quote.get("assessment_revision") != assessment["revision"]
        or type(quote.get("total_minor")) is not int
        or not 1 <= quote["total_minor"] <= 18_000_000_000_000
        or quote.get("currency") not in ("USD", "LBP")
    ):
        raise PublicError(
            "quote_required",
            "The buyer must accept this exact current quote.",
            status=409,
        )
    if (
        grant.get("subject_id") != str(row["buyer_id"])
        or grant.get("purpose") != "brand_approval"
        or grant.get("quote_id") != quote["id"]
        or grant.get("quote_revision") != quote["revision"]
        or type(grant.get("amount_minor")) is not int
        or grant.get("amount_minor") != quote["total_minor"]
        or grant.get("currency") != quote["currency"]
        or grant.get("status") != "valid"
        or grant.get("current") is not True
    ):
        raise PublicError(
            "grant_required", "Current quote-bound eligibility is required.", status=409
        )
    try:
        if not isinstance(grant.get("reviewer_id"), str):
            raise AccessDenied("An independent reviewer is required")
        reviewer_id = str(UUID(grant.get("reviewer_id")))
    except (ValueError, TypeError):
        raise AccessDenied("An independent reviewer is required") from None
    if reviewer_id in (str(approver_id), str(row["buyer_id"])):
        raise AccessDenied("An independent reviewer is required")
    for value in (quote, grant):
        try:
            expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                unavailable()
            if expires <= datetime.now(timezone.utc):
                raise PublicError(
                    "scope_expired", "Current approval scope has expired.", status=409
                )
        except (ValueError, TypeError, KeyError, AttributeError):
            unavailable()
    return {
        "request_id": str(row["id"]),
        "request_revision": row["revision"],
        "brand_id": str(row["brand_id"]),
        "subject_id": str(row["buyer_id"]),
        "approver_id": str(approver_id),
        "assessment_id": assessment["id"],
        "assessment_revision": assessment["revision"],
        "quote_id": quote["id"],
        "quote_revision": quote["revision"],
        "grant_id": grant["id"],
        "grant_revision": grant["revision"],
        "amount_minor": quote["total_minor"],
        "currency": quote["currency"],
        "purpose": "brand_approval",
    }


async def consume(request, operation_id, bindings):
    command = {"operation_id": str(operation_id), **bindings}
    prepared = await service_request(
        request,
        "eligibility",
        "POST",
        "/internal/v1/grants/prepare",
        headers={"Idempotency-Key": str(operation_id)},
        json=command,
    )
    if not isinstance(prepared, dict) or prepared.get("operation_id") != str(
        operation_id
    ):
        unavailable()
    if prepared.get("status") == "denied":
        raise PublicError(
            "grant_denied", "Current grant cannot authorize this decision.", status=409
        )
    if prepared.get("status") not in ("prepared", "succeeded"):
        unavailable()
    result = await service_request(
        request,
        "eligibility",
        "POST",
        "/internal/v1/grants/consume",
        headers={"Idempotency-Key": str(operation_id)},
        json=command,
    )
    # Unknown responses/revocation cannot be promoted into optimistic approval.
    if (
        not isinstance(result, dict)
        or result.get("operation_id") != str(operation_id)
        or result.get("status") != "succeeded"
        or result.get("current") is not True
        or any(result.get(key) != value for key, value in bindings.items())
    ):
        if isinstance(result, dict) and result.get("status") == "denied":
            raise PublicError(
                "grant_denied",
                "The grant no longer authorizes this decision.",
                status=409,
            )
        unavailable()
    return result
