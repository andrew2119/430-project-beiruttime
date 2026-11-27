"""Typed job allocation through the canonical watch and operation locks."""

import asyncio
import json

from bt_contracts.orders.allocation.guarded_v3 import CurrentJobDecision, JobBinding
from bt_contracts_core.errors import PublicError
from service_app.orders_kernel import command, lock_watch, order_fact, audit
from service_app.exact_quote import retain
from service_app.payment_notices import ensure_payment_notice


PROVIDER_TIMEOUT_SECONDS = 2


async def allocate_job(pool, binding: JobBinding, *, request_id, authority):
    """Authority consumes serialized current scope/grant permission in this transaction.

    A missing provider cannot allocate. The adapter must obtain bounded prepared
    producer facts before entering this transaction and validate/consume them here.
    """
    async def authorize(tx, recovery=False):
        if authority is None:
            raise PublicError("job_authority_unavailable", "Job authorization is pending. إذن العمل قيد الانتظار.", status=503)
        async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
            proof = CurrentJobDecision.model_validate(await authority.decision(tx, binding, recovery=recovery))
        if proof.binding != binding:
            raise PublicError("job_binding_mismatch", "The exact current job is required. يلزم طلب العمل الحالي المطابق.", status=409)
        if proof.state != "authorized":
            raise PublicError("job_authority_unavailable", "Job authorization is pending or denied. إذن العمل قيد الانتظار أو مرفوض.", status=503 if proof.state == "pending" else 403)
        return proof

    async def apply(tx):
        watch = await lock_watch(tx, binding.watch_id)
        if watch["revision"] != binding.expected_revision:
            return {"status": "denied", "code": "stale_revision", "message_en": "Reload the current watch.", "message_ar": "أعد تحميل الساعة الحالية.", "payment_authority": False}
        if watch["status"] != "available":
            return {"status": "denied", "code": "watch_committed", "message_en": "This watch already has an exclusive commitment.", "message_ar": "هذه الساعة مرتبطة بالتزام حصري بالفعل.", "payment_authority": False}
        proof = await authorize(tx)
        # The source identity is a physical watch, not another listing allocation.
        order = await tx.fetchrow(
            """INSERT INTO l08_orders(id,watch_id,listing_id,buyer_id,seller_id,organization_id,
            quote_id,state,currency,total_minor,deadline,is_demo,order_kind)
            VALUES($1,$2,$3,$4,$5,$6,$7,'awaiting_notification','USD',$8,NULL,$9,$10) RETURNING *""",
            binding.order_id, binding.watch_id, watch["listing_id"], binding.buyer_id,
            proof.seller_id, binding.organization_id, binding.quote_id, binding.total_minor,
            watch["is_demo"], binding.order_kind,
        )
        snapshot = proof.money.model_dump(mode="json") | {
            "id": str(binding.quote_id), "owner_id": str(binding.buyer_id),
            "revision": binding.quote_revision, "request_id": str(binding.request_id),
            "request_revision": binding.request_revision, "assessment_id": str(binding.assessment_id),
            "assessment_revision": binding.assessment_revision,
            "accepted_terms_revision": binding.accepted_terms_revision,
            "accepted_line_ids": [str(value) for value in binding.accepted_line_ids],
        }
        await retain(tx, order, snapshot, watch["listing_revision"], proof.seller_type)
        await tx.execute(
            "INSERT INTO l13_job_bindings(order_id,binding) VALUES($1,$2::jsonb)",
            binding.order_id, json.dumps(binding.model_dump(mode="json")),
        )
        await tx.execute(
            """UPDATE l08_watches SET status='reserved',source_id=$2,source_kind=$3,
            revision=revision+1 WHERE id=$1""", binding.watch_id, binding.order_id, binding.order_kind,
        )
        await ensure_payment_notice(tx, order, request_id)
        await audit(tx, binding.order_id, "user:" + str(binding.actor_id), "allocate-job",
                    "Exact accepted job scope and retained economics", order["revision"])
        return {"status": "succeeded", "order": order_fact(order), "payment_authority": False}

    async def current_access(tx, outcome):
        await authorize(tx, recovery=True)

    try:
        return await command(pool, "user:" + str(binding.actor_id), binding.operation_key,
                             "allocate-job", binding.model_dump(), apply,
                             request_id=request_id, retain_result=current_access)
    except TimeoutError:
        raise PublicError("job_authority_unavailable", "Job authorization timed out. Retry the same reference. انتهت مهلة إذن العمل. أعد المحاولة بالمرجع نفسه.", status=503) from None
