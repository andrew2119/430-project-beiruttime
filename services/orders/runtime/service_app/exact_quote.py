"""Versioned Pricing reads outside aggregate locks; submitted money is never authority."""

import json
from uuid import UUID
from datetime import datetime
from pydantic import ValidationError
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import PublicError
from .orders_dependencies import clients, delivery_headers


async def upstream(request, name, path, *, service_auth=False):
    response = await clients(request.app)[name].request(
        "GET",
        path,
        headers={
            "Authorization": request.headers.get("Authorization", ""),
            "X-Request-ID": request.state.request_id,
            **(delivery_headers(name) if service_auth else {}),
        },
    )
    if isinstance(response, Unavailable) or response.status_code >= 500:
        raise PublicError(
            name + "_unavailable", "A required current source is unavailable. Retry the same operation.", status=503
        )
    if response.status_code == 401:
        raise PublicError("unauthorized", "Sign in to continue.", status=401)
    if response.status_code != 200:
        raise PublicError(name + "_denied", "A current exact source is required.", status=409)
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise PublicError(name + "_unavailable", "The current source cannot be verified.", status=503) from None


def exact_snapshot(value, *, quote_id, buyer_id, listing_id, listing_revision, currency=None, total_minor=None):
    try:
        if (
            UUID(value["id"]) != quote_id
            or UUID(value["owner_id"]) != buyer_id
            or UUID(value["subject_id"]) != listing_id
            or value["subject_revision"] != listing_revision
            or value["source"] != "listing"
            or value["source_verified"] is not True
            or value["purpose"] != "purchase"
            or value["reviewed_at"] is None
            or type(value["revision"]) is not int
            or value["revision"] < 1
            or type(value["payable_minor"]) is not int
            or not 1 <= value["payable_minor"] <= 9000000000000000
            or value["currency"] not in ("USD", "LBP")
            or (currency is not None and value["currency"] != currency)
            or (total_minor is not None and value["payable_minor"] != total_minor)
        ):
            raise ValueError()
        expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            raise ValueError()
        for key in ("price_minor", "buyer_fee_minor", "shipping_minor", "tax_minor"):
            if type(value[key]) is not int or not 0 <= value[key] <= 9000000000000000:
                raise ValueError()
        if (
            sum(value[k] for k in ("price_minor", "buyer_fee_minor", "shipping_minor", "tax_minor"))
            != value["payable_minor"]
        ):
            raise ValueError()
        return json.loads(json.dumps(value)), expires
    except (KeyError, ValueError, TypeError):
        raise PublicError(
            "quote_binding_mismatch", "Review the exact current quote before continuing.", status=409
        ) from None


def current_quote(value):
    try:
        from bt_contracts.pricing.quotes.current import CurrentQuote

        return CurrentQuote.model_validate(value).model_dump(mode="json")
    except (ImportError, ValidationError):
        raise PublicError("pricing_unavailable", "The current quote contract cannot be verified.", status=503) from None


def retained_snapshot(value, current):
    """Normalize only the published financial DTO, never assessment/evidence prose.

    This historical read is NOT authorization. The caller has separately obtained
    CurrentQuote and must bind the same revision/source/buyer before allocating.
    """
    try:
        from bt_contracts.pricing.quotes.current import RetainedFinancialQuote
    except ImportError:
        raise PublicError(
            "pricing_unavailable", "The retained financial contract is unavailable.", status=503
        ) from None
    try:
        financial = RetainedFinancialQuote.model_validate(value).model_dump(mode="json")
        for field in (
            "quote_id",
            "quote_revision",
            "buyer_id",
            "currency",
            "schedule_id",
            "policy_revision",
            "rounding",
            "selected_line_ids",
            "terms_digest",
        ):
            if financial[field] != current[field]:
                raise ValueError()
        # Offers authorize the current offer aggregate, while its immutable
        # original Q01 financial quote remains bound to the listing revision.
        # The current offer expiry may also shorten the historical quote expiry.
        source_id = current["listing_id"] if current["kind"] == "offer" else current["source_id"]
        source_revision = current["listing_revision"] if current["kind"] == "offer" else current["source_revision"]
        retained_expiry = datetime.fromisoformat(financial["expires_at"])
        current_expiry = datetime.fromisoformat(current["expires_at"])
        if (
            financial["payable_minor"] != current["total_minor"]
            or financial["source_id"] != source_id
            or financial["source_revision"] != source_revision
            or (retained_expiry != current_expiry if current["kind"] != "offer" else retained_expiry < current_expiry)
        ):
            raise ValueError()
        return {
            **financial,
            "id": financial["quote_id"],
            "revision": financial["quote_revision"],
            "owner_id": financial["buyer_id"],
            "subject_id": financial["source_id"],
            "subject_revision": financial["source_revision"],
            "purpose": "purchase",
            "source": "auction" if current["kind"] in {"prebid", "winner"} else current["kind"],
            "source_verified": True,
            "kind": current["kind"],
            "authorization_source_id": current["source_id"],
            "authorization_source_revision": current["source_revision"],
            "authorization_expires_at": current["expires_at"],
        }
    except (ValidationError, ValueError, KeyError, TypeError):
        raise PublicError(
            "quote_binding_mismatch",
            "The retained exact allocation economics do not match current authorization.",
            status=409,
        ) from None


async def retain(tx, order, snapshot, listing_revision, seller_type):
    if seller_type not in ("private", "dealer", "brand") or (seller_type == "private") != (
        order["organization_id"] is None
    ):
        raise PublicError("seller_type_unknown", "The current seller route cannot be verified.", status=503)
    fields = ("price_minor", "buyer_fee_minor", "shipping_minor", "tax_minor")
    if (
        any(type(snapshot.get(k)) is not int or snapshot[k] < 0 for k in fields)
        or sum(snapshot[k] for k in fields) != order["total_minor"]
        or snapshot.get("id") != str(order["quote_id"])
        or snapshot.get("owner_id") != str(order["buyer_id"])
        or snapshot.get("currency") != order["currency"]
    ):
        raise PublicError("quote_binding_mismatch", "The retained exact fee lines do not match the order.", status=409)
    await tx.execute(
        """INSERT INTO l13_order_quotes(order_id,quote_id,quote_revision,listing_revision,seller_type,snapshot)
        VALUES($1,$2,$3,$4,$5,$6::jsonb)""",
        order["id"],
        order["quote_id"],
        snapshot["revision"],
        listing_revision,
        seller_type,
        json.dumps(snapshot),
    )
