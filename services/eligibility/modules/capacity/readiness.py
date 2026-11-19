"""Read-only exact payment readiness; historical task identity is preserved."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol


@dataclass(frozen=True)
class Context:
    operation_id: str
    actor_id: str
    organization_id: str
    subject_id: str
    watch_id: str
    buyer_id: str
    order_id: str
    order_kind: Literal["job"]
    quote_id: str
    quote_revision: int
    request_revision: int
    authority_revision: int
    payment_revision: int
    currency: Literal["USD"]
    total_minor: int


@dataclass(frozen=True)
class Payment:
    buyer_id: str
    order_id: str
    order_kind: str
    watch_id: str
    quote_id: str
    quote_revision: int
    currency: str
    total_minor: int
    payment_operation_id: str
    payment_revision: int
    state: str


@dataclass(frozen=True)
class Support:
    operation_id: str
    operator_id: str
    opened_at: str
    last_progress_at: str

    def deadlines(self, operation_id: str) -> tuple[str, str]:
        if self.operation_id != operation_id or not isinstance(self.operator_id, str) or not self.operator_id.strip():
            raise ValueError("A retained support assignment is required for this reference.")
        opened = datetime.fromisoformat(self.opened_at)
        progress = datetime.fromisoformat(self.last_progress_at)
        if opened.utcoffset() is None or progress.utcoffset() is None or progress < opened:
            raise ValueError("Support timestamps must be ordered and include a time zone.")
        return ((opened + timedelta(hours=24)).isoformat(), (progress + timedelta(hours=48)).isoformat())


class Source(Protocol):
    """Trusted adapters only; never accept these facts from a customer payload.

    Authority must recheck actor, business membership, assignment, subject,
    watch commitment, request revision and current accepted quote economics.
    It must compare every Context binding with its current authoritative source.
    Missing facts return None; revoked or stale bindings return False.
    """

    support: Support

    async def current_authority(self, context: Context) -> bool | None: ...

    async def orders_payment(self, context: Context) -> Payment | None: ...


MESSAGES = {
    "paid": ("Payment is held. Identity review remains separate.", "الدفعة محتجزة. تبقى مراجعة الهوية مستقلة."),
    "unpaid": ("Payment is unpaid. Open the job payment details.", "لم تُدفع الدفعة. افتح تفاصيل دفع العمل."),
    "pending": ("Readiness is pending. Retry the same reference.", "الجاهزية قيد الانتظار. أعد المحاولة بالمرجع نفسه."),
    "denied": ("Current details do not match. Reload the job.", "التفاصيل الحالية غير متطابقة. أعد تحميل العمل."),
}


async def read(context: Context, source: Source) -> dict:
    """Recheck authority and source on every invocation, including retries."""
    support = source.support
    review_at, escalate_at = support.deadlines(context.operation_id)
    state = "pending"
    reason = "source_unavailable"
    try:
        async with asyncio.timeout(1):
            authority = await source.current_authority(context)
            if authority is False:
                state, reason = "denied", "authority_denied"
            elif authority is True:
                values = asdict(context)
                integers = ("quote_revision", "request_revision", "authority_revision", "payment_revision", "total_minor")
                valid = all(type(values[key]) is int and values[key] > 0 for key in integers)
                valid = valid and all(type(value) is str and bool(value.strip()) for key, value in values.items() if key not in integers)
                if not valid or context.currency != "USD" or context.order_kind != "job" or context.subject_id != context.buyer_id:
                    state, reason = "denied", "invalid_context"
                else:
                    payment = await source.orders_payment(context)
                    if isinstance(payment, Payment):
                        bindings = ("buyer_id", "order_id", "order_kind", "watch_id", "quote_id", "quote_revision", "currency", "total_minor", "payment_revision")
                        exact = all(type(getattr(payment, key)) is type(values[key]) and getattr(payment, key) == values[key] for key in bindings)
                        if not exact:
                            state, reason = "denied", "payment_binding_mismatch"
                        elif type(payment.payment_operation_id) is not str or not payment.payment_operation_id.strip() or type(payment.state) is not str:
                            reason = "source_unavailable"
                        elif payment.state in {"paid_held", "unpaid"}:
                            state = "paid" if payment.state == "paid_held" else "unpaid"
                            reason = None
                        else:
                            reason = "payment_unknown"
    except (TimeoutError, ConnectionError):
        pass
    english, arabic = MESSAGES[state]
    action = (
        ("The assigned support operator must investigate within 24 hours and escalate after 48 hours without progress. Retry using the same reference.",
         "يجب على مسؤول الدعم المعيّن التحقق خلال ٢٤ ساعة والتصعيد بعد ٤٨ ساعة دون تقدم. أعد المحاولة باستخدام المرجع نفسه.")
        if state == "pending" else (english, arabic)
    )
    return {
        "schema_version": "eligibility.capacity.v1",
        **asdict(context),
        "expected_revision": context.request_revision,
        "revision": context.payment_revision,
        "state": state,
        "pending_reason": reason,
        "next_actor": support.operator_id if state == "pending" else context.actor_id,
        "next_review_at": review_at if state == "pending" else None,
        "escalate_at": escalate_at if state == "pending" else None,
        "next_action": {"en": action[0], "ar": action[1]},
        "message": {"en": english, "ar": arabic},
        "identity_pass": False,
        "execution_authorized": False,
    }
