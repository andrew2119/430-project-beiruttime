"""Bounded ordinary colleague transitions; callers persist the whole result atomically."""
from dataclasses import dataclass, replace
from uuid import UUID

ORDINARY = frozenset({"business.stock.write", "business.jobs.write", "business.records.read"})


class AdministrationDenied(ValueError):
    pass


@dataclass(frozen=True)
class Member:
    subject_id: UUID
    business_id: UUID
    permissions: frozenset[str]
    revision: int = 1
    state: str = "active"


@dataclass(frozen=True)
class Administration:
    actor: Member
    business_id: UUID
    business_active: bool
    ceiling: frozenset[str]
    ceiling_revision: int


@dataclass(frozen=True)
class Job:
    job_id: UUID
    business_id: UUID
    responsible_id: UUID
    revision: int
    active: bool = True


@dataclass(frozen=True)
class StaffResult:
    member: Member
    jobs: tuple[Job, ...]
    reason: str
    ceiling_revision: int


def authorize(authority, subject_id, business_id, permissions, *, kind="grant"):
    actor = authority.actor
    if (not authority.business_active or actor.state != "active"
            or actor.business_id != business_id or authority.business_id != business_id
            or "business.staff.manage" not in actor.permissions):
        raise AdministrationDenied("current_business_administrator_required")
    if actor.subject_id == subject_id:
        raise AdministrationDenied("self_intervention_denied")
    if not permissions <= ORDINARY or (kind == "grant" and not permissions <= authority.ceiling):
        raise AdministrationDenied("platform_ceiling_exceeded")


def change(authority, subject_id, business_id, expected_revision, kind, permissions,
           reason, *, existing=None, jobs=(), replacement=None, responsibilities_current=False):
    permissions = frozenset(permissions)
    authorize(authority, subject_id, business_id, permissions, kind=kind)
    if not 5 <= len(reason.strip()) <= 500:
        raise AdministrationDenied("reason_required")
    if kind not in {"grant", "suspend", "remove"}:
        raise AdministrationDenied("invalid_transition")
    if existing is not None:
        if existing.subject_id != subject_id or existing.business_id != business_id:
            raise AdministrationDenied("wrong_business")
        if not existing.permissions <= ORDINARY:
            raise AdministrationDenied("privileged_membership_denied")
        if existing.revision != expected_revision:
            raise AdministrationDenied("stale_revision")
    elif kind != "grant" or expected_revision != 0:
        raise AdministrationDenied("stale_revision")
    # A missing responsibility provider is never an empty list of active jobs.
    if not responsibilities_current:
        raise AdministrationDenied("responsibilities_unavailable")
    if any(job.business_id != business_id for job in jobs):
        raise AdministrationDenied("wrong_business")
    affected = tuple(job for job in jobs if job.active and job.responsible_id == subject_id)
    losing_jobs = kind != "grant" or "business.jobs.write" not in permissions
    if affected and losing_jobs:
        if (replacement is None or replacement.state != "active"
                or replacement.business_id != business_id
                or replacement.subject_id == subject_id
                or "business.jobs.write" not in replacement.permissions):
            raise AdministrationDenied("responsible_replacement_required")
        jobs = tuple(replace(job, responsible_id=replacement.subject_id, revision=job.revision + 1)
                     if job in affected else job for job in jobs)
    state = {"grant": "active", "suspend": "suspended", "remove": "revoked"}[kind]
    member = Member(subject_id, business_id,
                    permissions if kind == "grant" else existing.permissions,
                    expected_revision + 1, state)
    return StaffResult(member, tuple(jobs), reason.strip(), authority.ceiling_revision)


def responsibility_reducing(row, body):
    """Legacy edits cannot remove responsibility without current replacement facts."""
    return (body.state != "active"
            or (body.capabilities is not None
                and not set(row["capabilities"]) <= set(body.capabilities))
            or (body.qualifications is not None
                and not set(row["qualifications"]) <= set(body.qualifications))
            or (body.intervention_scope is not None
                and body.intervention_scope != row["intervention_scope"]))
