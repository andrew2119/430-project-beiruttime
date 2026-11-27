"""One verifier, one transaction and one balanced journal for simulated money."""

import hashlib
import json
from uuid import UUID, uuid4
from bt_contracts.orders.payments import PaymentCallback
from bt_contracts.orders.payments.signatures import secret as secret, sign as sign, verify_payload
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from service_app.orders_kernel import lock_order, audit, decoded


def verify(raw, signature):
    return verify_payload(raw, signature, PaymentCallback)


def project(row):
    return {
        key: str(row[key]) if isinstance(row[key], UUID) else row[key]
        for key in (
            "id",
            "order_id",
            "buyer_id",
            "quote_id",
            "quote_revision",
            "route",
            "reference",
            "currency",
            "total_minor",
            "state",
            "sequence",
        )
    } | {"simulated": True}


async def recovery_operator(tx, order):
    operator = await tx.fetchval(
        'SELECT operator_id FROM l13_payment_recovery_assignments WHERE order_id=$1 FOR UPDATE',
        order['id'])
    if operator is None or operator == order['buyer_id']:
        raise PublicError('recovery_assignment_unavailable',
            'Payment recovery assignment is unavailable. تعيين مسؤول معالجة الدفع غير متاح.', status=503)
    return operator


async def process_receipt(tx, body, request_id):
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    await tx.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
        "l13-callback:" + str(body.event_id),
    )
    prior = await tx.fetchrow(
        "SELECT * FROM l13_payment_callbacks WHERE event_id=$1", body.event_id
    )
    if prior:
        if prior["digest"] != digest:
            raise PublicError(
                "callback_conflict",
                "This callback ID has different content.",
                status=409,
            )
        return decoded(prior["outcome"])
    preliminary = await tx.fetchrow(
        "SELECT * FROM l13_payment_attempts WHERE id=$1", body.attempt_id
    )
    if preliminary is None:
        raise PublicError("attempt_unknown", "Payment attempt not found.", status=404)
    order = await lock_order(tx, preliminary["order_id"])
    attempt = await tx.fetchrow(
        "SELECT * FROM l13_payment_attempts WHERE id=$1 FOR UPDATE", body.attempt_id
    )
    for name in (
        "order_id",
        "buyer_id",
        "quote_id",
        "quote_revision",
        "route",
        "reference",
        "currency",
        "total_minor",
    ):
        if getattr(body, name) != attempt[name]:
            raise PublicError(
                "callback_binding_mismatch",
                "This result does not match the retained attempt.",
                status=409,
            )
    if (
        order["total_minor"] != attempt["total_minor"]
        or order["currency"] != attempt["currency"]
        or order["quote_id"] != attempt["quote_id"]
    ):
        raise PublicError(
            "order_binding_mismatch",
            "The exact order binding does not match.",
            status=409,
        )
    newer = await tx.fetchval(
        "SELECT 1 FROM l13_payment_attempts WHERE order_id=$1 AND (created_at,id)>($2,$3)",
        order["id"],
        attempt["created_at"],
        attempt["id"],
    )
    review = await tx.fetchval(
        'SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', order['id'])
    conflicting = body.outcome != 'declined' and (
        attempt['state'] == 'declined' or newer or order['state'] == 'expired_released')
    if conflicting and not review:
        operator = await recovery_operator(tx, order)
        await tx.execute(
            """INSERT INTO l13_money_reconciliations(event_id,attempt_id,order_id,buyer_contact_id,next_actor,next_action)
            VALUES($1,$2,$3,$4,$5,'reconcile_original_payment')""", body.event_id, attempt['id'], order['id'], order['buyer_id'], operator)
        # A held original attempt keeps the existing expiry policy from releasing stock.
        attempt = await tx.fetchrow(
            "UPDATE l13_payment_attempts SET state='held',sequence=GREATEST(sequence,$2),updated_at=clock_timestamp() WHERE id=$1 RETURNING *",
            attempt['id'], body.sequence)
        await tx.execute('UPDATE l08_orders SET financial_revision=financial_revision+1 WHERE id=$1', order['id'])
        await enqueue(tx, EventEnvelope(type='orders.payment-reconciliation.v3', source='orders',
            subject=str(order['id']), request_id=request_id,
            data={'order_id': str(order['id']), 'attempt_id': str(attempt['id']), 'simulated': True}),
            ['communications-order-timeline'])
        review = True
    if review:
        result = {'status': 'pending', 'code': 'reconciliation_required',
                  'attempt': project(attempt), 'paid': False}
    elif attempt["state"] == "confirmed" or body.sequence <= attempt["sequence"]:
        result = {
            "status": "succeeded",
            "code": "already_reconciled",
            "attempt": project(attempt),
            "paid": order["state"] == "paid_held",
        }
    elif newer or order['state'] in {'expired_released', 'paid_held'} or attempt['state'] == 'declined':
        result = {'status': 'pending', 'code': 'reconciliation_required',
                  'attempt': project(attempt), 'paid': False}
    else:
        state = body.outcome
        now = await tx.fetchval("SELECT clock_timestamp()")
        pricing_state = await tx.fetchval("SELECT state FROM l13_quote_commitments WHERE order_id=$1", order["id"])
        if order["currency"] != "USD" or (state != "declined" and pricing_state == "reconciliation") or (
            state != "declined"
            and (order["state"] == "expired_fenced" or order["deadline"] is None or now >= order["deadline"])
        ):
            state = "held"
        if state == "confirmed":
            group_id = uuid4()
            await tx.execute(
                """INSERT INTO l13_journal_groups(id,order_id,attempt_id,currency,total_minor)
                VALUES($1,$2,$3,$4,$5)""",
                group_id,
                order["id"],
                attempt["id"],
                attempt["currency"],
                attempt["total_minor"],
            )
            await tx.executemany(
                "INSERT INTO l13_journal_entries(group_id,account,amount_minor) VALUES($1,$2,$3)",
                [
                    (group_id, "simulated_clearing", attempt["total_minor"]),
                    (group_id, "buyer_held", -attempt["total_minor"]),
                ],
            )
            order = await tx.fetchrow(
                "UPDATE l08_orders SET state='paid_held',revision=revision+1 WHERE id=$1 RETURNING *",
                order["id"],
            )
            await audit(
                tx,
                order["id"],
                "service:orders",
                "payment-confirmed",
                "Exact signed simulated funds held; no payout",
                order["revision"],
            )
            # Source facts and destinations are explicit; receivers enable their named subscription.
            await enqueue(
                tx,
                EventEnvelope(
                    type="orders.payment-confirmed.v1",
                    source="orders",
                    subject=str(order["id"]),
                    request_id=request_id,
                    data={
                        "order_id": str(order["id"]),
                        "watch_id": str(order["watch_id"]),
                        "listing_id": str(order["listing_id"]),
                        "buyer_id": str(order["buyer_id"]),
                        "seller_id": str(order["seller_id"]),
                        "organization_id": str(order["organization_id"])
                        if order["organization_id"]
                        else None,
                        "revision": order["revision"],
                        "quote_id": str(order["quote_id"]),
                        "currency": order["currency"],
                        "total_minor": order["total_minor"],
                        "journal_group_id": str(group_id),
                        "simulated": True,
                    },
                ),
                ["communications-order-timeline"],
            )
        elif state == "declined" and order["state"] == "expired_fenced":
            # A conclusive final decline makes the original expiry eligible for safe release.
            await tx.execute("UPDATE l08_orders SET state='payment_unknown',revision=revision+1 WHERE id=$1", order["id"])
        elif state in {"pending", "held"}:
            if order["state"] == "awaiting_payment":
                await tx.execute(
                    "UPDATE l08_orders SET state='payment_unknown',revision=revision+1 WHERE id=$1",
                    order["id"],
                )
        attempt = await tx.fetchrow(
            "UPDATE l13_payment_attempts SET state=$2,sequence=$3,updated_at=clock_timestamp() WHERE id=$1 RETURNING *",
            attempt["id"],
            state,
            body.sequence,
        )
        result = {
            "status": "pending" if state in {"pending", "held"} else "succeeded",
            "code": "reconciliation_required" if state == "held" else state,
            "attempt": project(attempt),
            "paid": state == "confirmed",
        }
    await tx.execute(
        "INSERT INTO l13_payment_callbacks(event_id,attempt_id,digest,outcome) VALUES($1,$2,$3,$4::jsonb)",
        body.event_id,
        body.attempt_id,
        digest,
        json.dumps(result),
    )
    return result


async def current_payment_result(tx, order_id, value):
    order = await lock_order(tx, order_id)
    changed = await tx.fetchval(
        """SELECT EXISTS(SELECT 1 FROM l13_money_operations WHERE order_id=$1
        AND kind IN ('refund','release') AND state<>'declined') OR EXISTS(
        SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1)""", order_id)
    review = await tx.fetchval('SELECT 1 FROM l13_money_reconciliations WHERE order_id=$1', order_id)
    return value | ({'status': 'pending', 'code': 'reconciliation_required'} if review else {}) | {'paid': bool(value.get('paid')) and order['state'] == 'paid_held' and not changed,
                    'payment_revision': order['revision'] + order.get('financial_revision', 0)}


async def process(tx, body, request_id):
    receipt = await process_receipt(tx, body, request_id)
    return await current_payment_result(tx, body.order_id, receipt)
