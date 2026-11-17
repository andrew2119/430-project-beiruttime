"""Prerequisite check only. Canonical Orders must recheck before journal release."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class ReleaseFacts:
    job_id: str
    watch_id: str
    scope_revision: int
    work_revision: int
    quality_scope_revision: int
    quality_work_revision: int
    quality_reviewer_id: str
    assessor_id: str
    approver_id: str
    quality_assignment_current: bool
    quality_passed: bool
    tests_recorded: bool
    fit_recorded: bool
    returned_parts_recorded: bool
    receipt_job_id: str
    receipt_watch_id: str
    receipt_actual: bool
    authorized_recipient: bool
    received_at: datetime | None
    dispute_clear: bool
    incident_clear: bool
    holds_clear: bool


def release_ready(facts: ReleaseFacts, now: datetime) -> bool:
    """Use authoritative UTC instants, including equality at the window end."""
    receipt = facts.received_at
    if receipt is None or now.tzinfo != timezone.utc or receipt.tzinfo != timezone.utc:
        return False
    if receipt > now or now < receipt + timedelta(hours=168):
        return False
    if (facts.receipt_job_id, facts.receipt_watch_id) != (facts.job_id, facts.watch_id):
        return False
    if (facts.quality_scope_revision, facts.quality_work_revision) != (facts.scope_revision, facts.work_revision):
        return False
    if not facts.quality_reviewer_id or facts.quality_reviewer_id in (facts.assessor_id, facts.approver_id):
        return False
    return all(value is True for value in (
        facts.quality_assignment_current, facts.quality_passed, facts.tests_recorded,
        facts.fit_recorded, facts.returned_parts_recorded, facts.receipt_actual,
        facts.authorized_recipient, facts.dispute_clear, facts.incident_clear, facts.holds_clear,
    ))
