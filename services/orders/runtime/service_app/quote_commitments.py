"""Retry Pricing's original allocation attestation outside every aggregate lock."""

import json
from datetime import datetime
from uuid import uuid4

import jwt
from pydantic import ValidationError
from bt_bulkheads import Unavailable
from bt_contracts.orders.allocation.quote_commitment import QuoteCommitment
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from .orders_dependencies import delivery_headers
from .orders_kernel import audit, decoded, lock_order, record_fact


def attestation(order, snapshot, committed_at):
    try:
        body = QuoteCommitment(buyer_id=order["buyer_id"], order_id=order["id"],
                               quote_revision=snapshot["revision"], total_minor=order["total_minor"],
                               committed_at=committed_at)
        reviewed = datetime.fromisoformat(snapshot["reviewed_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(snapshot["expires_at"].replace("Z", "+00:00"))
        if (order["currency"] != "USD" or snapshot["currency"] != "USD"
                or snapshot["id"] != str(order["quote_id"])
                or snapshot["owner_id"] != str(order["buyer_id"])
                or type(snapshot["payable_minor"]) is not int
                or snapshot["payable_minor"] != order["total_minor"]
                or reviewed.tzinfo is None or expires.tzinfo is None
                or not reviewed <= body.committed_at < expires):
            raise ValueError()
        return body.model_dump(mode="json")
    except (ValidationError, KeyError, ValueError, TypeError, AttributeError):
        raise PublicError("quote_commitment_mismatch", "The original reviewed allocation must be retained exactly.", status=409) from None


async def retain_commitment(tx, order, snapshot, committed_at):
    body = attestation(order, snapshot, committed_at)
    inserted = await tx.fetchval(
        """INSERT INTO l13_quote_commitments(order_id,quote_id,payload) VALUES($1,$2,$3::jsonb)
        ON CONFLICT(order_id) DO NOTHING RETURNING 1""", order["id"], order["quote_id"], json.dumps(body),
    )
    if not inserted:
        prior = await tx.fetchrow("SELECT quote_id,payload FROM l13_quote_commitments WHERE order_id=$1", order["id"])
        if prior is None or prior["quote_id"] != order["quote_id"] or decoded(prior["payload"]) != body:
            raise PublicError("quote_commitment_conflict", "Retry the original allocation attestation without changing it.", status=409)


def result_state(status):
    if status in (200, 201):
        return "acknowledged", None
    if status in (400, 409, 410, 422):
        return "reconciliation", "pricing_commitment_refused"
    return "pending", "pricing_commitment_unavailable"


async def confirm(pricing, row):
    """A successful transport alone is not proof of committed economics."""
    body = decoded(row["payload"])
    try:
        binding = QuoteCommitment.model_validate(body)
    except ValueError:
        return "reconciliation", "retained_commitment_invalid", None
    if binding.order_id != row["order_id"]:
        return "reconciliation", "retained_commitment_invalid", None
    headers = {**delivery_headers("pricing"), "Idempotency-Key": "quote-commit:" + str(row["order_id"]),
               "X-Request-ID": "quote-commit-" + str(row["order_id"])}
    response = await pricing.request("POST", f"/internal/v3/quotes/{row['quote_id']}/commit", headers=headers, json=body)
    status = None if isinstance(response, Unavailable) else response.status_code
    state, code = result_state(status)
    if state != "acknowledged":
        return state, code, None
    try:
        outcome = response.json()
    except ValueError:
        outcome = None  # The contract does not require a POST response representation.
    if isinstance(outcome, dict):
        if outcome.get("status") == "denied":
            return "reconciliation", "pricing_commitment_refused", None
        if "status" in outcome and outcome.get("status") not in ("succeeded", "valid"):
            return "pending", "pricing_commitment_unavailable", None
    validation = await pricing.request(
        "GET", f"/internal/v3/quotes/{row['quote_id']}/validation?buyer_id={body['buyer_id']}", headers=headers,
    )
    if isinstance(validation, Unavailable) or validation.status_code != 200:
        return "pending", "pricing_commitment_unverified", None
    try:
        from .exact_quote import current_quote

        proof = current_quote(validation.json())
    except (PublicError, ValueError, TypeError):
        return "pending", "pricing_commitment_unverified", None
    expected = {"quote_id": str(row["quote_id"]), "buyer_id": body["buyer_id"],
                "quote_revision": body["quote_revision"], "total_minor": body["total_minor"], "kind": "purchase"}
    if any(proof.get(key) != value for key, value in expected.items()):
        return "reconciliation", "pricing_commitment_mismatch", None
    return "acknowledged", None, proof


async def relay_commitments(pool, pricing):
    lease = uuid4()
    async with unit_of_work(pool) as tx:
        rows = await tx.fetch(
            """UPDATE l13_quote_commitments SET lease=$1,lease_until=clock_timestamp()+interval '30 seconds',attempts=attempts+1
            WHERE order_id IN (SELECT order_id FROM l13_quote_commitments WHERE state='pending'
            AND next_attempt_at<=clock_timestamp() AND (lease_until IS NULL OR lease_until<=clock_timestamp())
            ORDER BY next_attempt_at,order_id LIMIT 5 FOR UPDATE SKIP LOCKED) RETURNING *""", lease,
        )
    for row in rows:
        state, code, proof = "pending", "pricing_commitment_unavailable", None
        try:
            state, code, proof = await confirm(pricing, row)
        except (RuntimeError, ValueError, jwt.PyJWTError):
            # Missing/rotating service credentials never manufacture an acknowledgment.
            pass
        async with unit_of_work(pool) as tx:
            # Same order-before-intent lock order as checkout's guarded commands.
            order = await lock_order(tx, row["order_id"])
            if state == "acknowledged":
                retained_revision = await tx.fetchval("SELECT listing_revision FROM l13_order_quotes WHERE order_id=$1", row["order_id"])
                if proof is None or proof["source_id"] != str(order["listing_id"]) or proof["source_revision"] != retained_revision:
                    state, code = "reconciliation", "pricing_commitment_mismatch"
            wrote = await tx.fetchval(
                """UPDATE l13_quote_commitments SET state=$3,last_error=$4,lease=NULL,lease_until=NULL,
                acknowledged_at=CASE WHEN $3='acknowledged' THEN clock_timestamp() ELSE NULL END,
                next_attempt_at=clock_timestamp()+interval '5 seconds'
                WHERE order_id=$1 AND lease=$2 AND state='pending' RETURNING 1""",
                row["order_id"], lease, state, code,
            )
            if wrote and state != "pending":
                await audit(tx, row["order_id"], "service:pricing", "pricing-commitment-" + state,
                            "Original fixed-price allocation acknowledged" if state == "acknowledged"
                            else "Original quote commitment refused; operator reconciliation required", order["revision"])
                await record_fact(tx, "quote-commit-" + str(row["order_id"]), "pricing-commitment-" + state,
                                  row["order_id"], order["revision"],
                                  {"order_id": str(row["order_id"]), "quote_id": str(row["quote_id"]), "outcome": state,
                                   "next_action": "none" if state == "acknowledged" else "operator_reconciliation"})
    return len(rows)
