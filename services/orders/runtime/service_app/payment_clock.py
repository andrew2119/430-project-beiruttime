"""Notified, method-bound payment windows. All comparisons use server UTC time."""

from datetime import timedelta

HOURS = {None: 48, "card": 24, "whish": 48, "omt": 48}
UNRESOLVED = {"pending", "held", "confirmed"}


def deadline_for(notified_at, method=None, extended_until=None):
    if notified_at is None:
        return None
    base = notified_at + timedelta(hours=HOURS[method])
    return max(base, extended_until) if extended_until else base


def can_initiate(order, method, now):
    deadline = deadline_for(
        order.get("notified_at"), method, order.get("initiation_extended_until")
    )
    return (
        order["currency"] == "USD"
        and order["state"] in {"awaiting_payment", "payment_unknown"}
        and deadline is not None
        and order.get("deadline") is not None
        and now < min(deadline, order["deadline"])
    )


def initiated_until(order, method, now):
    """One extra action window, never renewed by retry or switching method."""
    if not can_initiate(order, method, now):
        return None
    return order.get("initiation_extended_until") or (
        deadline_for(order["notified_at"], method) + timedelta(hours=24)
    )


def expiry_decision(order, attempts, now):
    if order["currency"] != "USD":
        return "hold"  # Historical committed currency needs explicit reconciliation.
    deadline = order.get("deadline")
    if deadline is None or now < deadline:
        return "wait"
    if order["state"] not in {"awaiting_payment", "payment_unknown", "expired_fenced"}:
        return "wait"
    return "hold" if any(a["state"] != "declined" for a in attempts) else "release"
