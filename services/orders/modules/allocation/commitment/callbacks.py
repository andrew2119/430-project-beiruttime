"""Order-first entry to the existing signed callback journal boundary."""

from bt_contracts_core.errors import PublicError
from service_app.orders_kernel import lock_order


async def apply_callback(tx, body, request_id, process):
    # No callback/event lock may be held before the canonical order lock.
    # Resolve from the retained attempt, never from an untrusted callback order id.
    order_id = await tx.fetchval(
        "SELECT order_id FROM l13_payment_attempts WHERE id=$1", body.attempt_id
    )
    if order_id is None:
        raise PublicError("attempt_unknown", "Payment attempt not found. لم يتم العثور على محاولة الدفع.", status=404)
    await lock_order(tx, order_id)
    return await process(tx, body, request_id)
