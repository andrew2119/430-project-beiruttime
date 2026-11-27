"""Sole transaction entry points for current custody and journal producers.

The producers run in this same transaction. They own their published guards;
no caller-supplied decision, cached paid flag or local balance is authority.
"""

import asyncio
import hashlib
import json
from datetime import timedelta
from typing import Protocol

from bt_contracts.orders.allocation.guarded_v3 import (
    Binding, CurrentDecision, CustodyCommand, FinancialCommand, GuardedResult,
)
from bt_contracts_core.errors import PublicError
from service_app.orders_kernel import command, lock_order, operation, paid_fact


class CurrentAuthority(Protocol):
    async def decision(self, tx, binding: Binding, *, recovery: bool) -> CurrentDecision: ...


class TransactionBoundary(Protocol):
    async def apply(self, tx, binding: Binding, decision: CurrentDecision) -> GuardedResult:
        """Check current source facts, reserve/post once and append the atomic outbox."""
        ...


PROVIDER_TIMEOUT_SECONDS = 2


class PendingBoundary(Exception):
    pass


def result(binding, revision, status, code, next_actor, next_review_at):
    messages = {
        "stale_revision": ("Reload the current order.", "أعد تحميل الطلب الحالي."),
        "current_authority_denied": ("Current permission is required. يلزم الإذن الحالي.", "يلزم الإذن الحالي."),
        "prerequisite_unavailable": (
            "The operation is pending review. Retry the same reference.",
            "العملية قيد المراجعة. أعد المحاولة بالمرجع نفسه.",
        ),
    }
    en, ar = messages[code]
    return GuardedResult(operation_key=binding.operation_key, revision=revision, status=status,
                         code=code, message_en=en, message_ar=ar,
                         next_actor=next_actor, next_review_at=next_review_at).model_dump(mode="json")


async def execute(pool, binding, *, request_id, authority, boundary, responsible_actor):
    """Authenticated adapters supply the selected current actor and producer ports.

    Timeout must roll back this transaction. A caller retries this exact key and
    payload; a pending prerequisite never becomes a permanently cached success.
    """
    actor_key = "user:" + str(binding.actor_id)

    async def authorize(tx, *, recovery):
        if authority is None:
            raise PendingBoundary()
        async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
            decision = CurrentDecision.model_validate(await authority.decision(tx, binding, recovery=recovery))
        if decision.binding != binding:
            raise PublicError("authority_binding_mismatch", "The exact current decision is required. يلزم القرار الحالي المطابق.", status=409)
        if decision.state == "pending":
            raise PendingBoundary()
        if recovery and decision.state != "authorized":
            raise PublicError("current_authority_denied", "Current permission is required. يلزم الإذن الحالي.", status=403)
        return decision

    async def apply(tx):
        order = await lock_order(tx, binding.order_id)
        decision = await authorize(tx, recovery=False)
        common = dict(next_actor=decision.next_actor, next_review_at=decision.next_review_at)
        if decision.state != "authorized":
            return result(binding, order["revision"], "denied", "current_authority_denied", **common)
        if order["revision"] != binding.expected_revision:
            return result(binding, order["revision"], "denied", "stale_revision", **common)
        if (order["watch_id"] != binding.watch_id or order["quote_id"] != binding.quote_id
                or order["organization_id"] != binding.organization_id or order["currency"] != "USD"):
            raise PublicError("order_binding_mismatch", "The exact current order is required. يلزم الطلب الحالي المطابق.", status=409)
        if boundary is None:
            raise PendingBoundary()
        if isinstance(binding, FinancialCommand):
            fact = await paid_fact(tx, binding.order_id, version=2)
            money = fact.get("retained_economics")
            if (not fact["paid"] or money is None or fact["quote_revision"] != binding.quote_revision):
                raise PendingBoundary()
            maximum = money["refundable_max_minor"] if binding.kind == "refund" else money["seller_net_minor"]
            recipient = order["buyer_id"] if binding.kind == "refund" else order["seller_id"]
            if binding.recipient_id != recipient or binding.amount_minor > maximum:
                raise PublicError("financial_binding_mismatch", "The retained recipient and principal are required. يلزم المستفيد والمبلغ الأصلي المحفوظان.", status=409)
            if binding.kind == "release" and binding.amount_minor != maximum:
                raise PublicError("release_amount_mismatch", "The retained net release is required. يلزم صافي التحويل المحفوظ.", status=409)
        elif isinstance(binding, CustodyCommand):
            now = await tx.fetchval("SELECT clock_timestamp()")
            if binding.received_at > now:
                raise PublicError("invalid_receipt_time", "Actual receipt cannot be in the future. لا يمكن تسجيل الاستلام الفعلي في المستقبل.", status=409)
        else:
            raise PublicError("command_unavailable", "This command is unavailable. هذا الإجراء غير متاح.", status=409)
        async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
            outcome = GuardedResult.model_validate(await boundary.apply(tx, binding, decision))
        if outcome.operation_key != binding.operation_key or outcome.revision < order["revision"]:
            raise PublicError("outcome_binding_mismatch", "The original operation outcome is required. تلزم النتيجة الأصلية للعملية.", status=409)
        if outcome.status == "pending":
            # The boundary must throw for uncertain writes so the shared transaction
            # rolls back; a durable pending journal reservation returns succeeded.
            raise PendingBoundary()
        return outcome.model_dump(mode="json")

    async def current_access(tx, outcome):
        # command calls this hook on exact replay as well as first execution.
        await authorize(tx, recovery=True)

    try:
        return await command(pool, actor_key, binding.operation_key, binding.kind,
                             binding.model_dump(), apply, request_id=request_id,
                             retain_result=current_access)
    except (PendingBoundary, TimeoutError):
        from datetime import datetime, timezone

        return result(binding, binding.expected_revision, "pending", "prerequisite_unavailable",
                      responsible_actor, datetime.now(timezone.utc) + timedelta(hours=24))


async def lookup(pool, binding, *, authority):
    """Receipt lookup rechecks current private access and never grants execution."""
    from bt_runtime.app.db import unit_of_work

    async with unit_of_work(pool) as tx:
        await lock_order(tx, binding.order_id)
        if authority is None:
            raise PublicError("authority_unavailable", "Current permission is unavailable. الإذن الحالي غير متاح.", status=503)
        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
                proof = CurrentDecision.model_validate(await authority.decision(tx, binding, recovery=True))
        except TimeoutError:
            raise PublicError("authority_unavailable", "Current permission is unavailable. Retry the same reference. الإذن الحالي غير متاح. أعد المحاولة بالمرجع نفسه.", status=503) from None
        if proof.binding != binding or proof.state != "authorized":
            raise PublicError("current_authority_denied", "Current permission is required. يلزم الإذن الحالي.", status=403)
        actor_key = "user:" + str(binding.actor_id)
        retained = await tx.fetchrow(
            "SELECT digest FROM l08_operations WHERE actor_key=$1 AND idempotency_key=$2",
            actor_key, binding.operation_key,
        )
        digest = hashlib.sha256(json.dumps(
            {"action": binding.kind, "body": binding.model_dump()}, sort_keys=True,
            separators=(",", ":"), default=str,
        ).encode()).hexdigest()
        if retained is None:
            return None
        if retained["digest"] != digest:
            raise PublicError("idempotency_conflict", "This operation key has different content. يحتوي مرجع العملية على محتوى مختلف.", status=409)
        return await operation(tx, actor_key, binding.operation_key)


async def refund(pool, binding: FinancialCommand, **kwargs):
    if binding.kind != "refund":
        raise ValueError("A refund command is required")
    return await execute(pool, binding, **kwargs)


async def release(pool, binding: FinancialCommand, **kwargs):
    if binding.kind != "release":
        raise ValueError("A release command is required")
    return await execute(pool, binding, **kwargs)


async def custody(pool, binding: CustodyCommand, **kwargs):
    return await execute(pool, binding, **kwargs)
