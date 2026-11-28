"""Pure decisions; only the canonical Orders transaction may act on them."""
from datetime import datetime, timedelta
from .contracts import Command, Snapshot, Preview


def closes_at(source: Snapshot):
    return source.receipt.received_at + timedelta(hours=source.dispute_window_hours) if source.receipt else None


def conditions(source: Snapshot, now: datetime, command: Command | None = None) -> tuple[str, ...]:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("utc_required")
    missing = []
    if command:
        if command.expected_revision != source.revision:
            missing.append("stale_revision")
        pairs = (
            ("subject_id", "subject_id"), ("watch_id", "watch_id"), ("organization_id", "organization_id"),
            ("quote_id", "quote_id"), ("quote_revision", "quote_revision"),
            ("policy_revision", "policy_revision"), ("recipient_id", "recipient_id"),
            ("recipient_revision", "recipient_revision"),
        )
        if any(getattr(command, a) != getattr(source, b) for a, b in pairs):
            missing.append("binding_changed")
    if not source.sources_current:
        missing.append("sources_unavailable")
    minimum_window = 72 if source.kind == "private_watch" else 168
    if not source.accepted_economics or not source.accepted_fee_line or source.dispute_window_hours < minimum_window:
        missing.append("economics_unaccepted")
    if source.payment_state != "paid_held" or not source.payment_operation_id or not source.payment_revision:
        missing.append("payment_not_held")
    if source.held_principal_minor != source.principal_minor:
        missing.append("principal_unavailable")
    if source.refund_reserved_minor or source.refunded_minor:
        missing.append("refund_active")
    if not source.recipient_verified or source.recipient_owner_id != source.seller_id:
        missing.append("recipient_unverified")
    if source.kind == "private_watch":
        if not all((source.inspection_current, source.inspection_pass, source.inspection_independent,
                    source.inspection_actual_custody)):
            missing.append("inspection_required")
    elif source.kind in ("dealer_watch", "brand_watch"):
        if not source.assurance_current:
            missing.append("assurance_required")
    else:
        people = (source.assessor_id, source.approver_id, source.quality_reviewer_id)
        if not all((source.quality_current, source.quality_pass, source.quality_actual_tests,
                    source.quality_fit_checked, source.quality_returned_parts_checked)) or (
                    None in people or len(set(people)) != 3):
            missing.append("quality_required")
    receipt = source.receipt
    if not receipt or not all((
        receipt.order_id == source.subject_id,
        receipt.watch_id == source.watch_id,
        receipt.watch_revision == source.watch_revision,
        receipt.authorized_recipient == source.buyer_id,
        receipt.recipient == receipt.authorized_recipient,
        receipt.kind != "dispatch",
        receipt.approved,
        receipt.received_at <= now,
    )):
        missing.append("receipt_required")
    if receipt and now < closes_at(source):
        missing.append("window_open")
    if source.hold_state != "clear":
        missing.append("hold_unknown" if source.hold_state == "unknown" else "hold_active")
    if source.active_release_operation_id:
        missing.append("release_exists")
    return tuple(missing)


def preview(source: Snapshot, now: datetime) -> Preview:
    return Preview(snapshot=source, missing=conditions(source, now), closes_at=closes_at(source))
