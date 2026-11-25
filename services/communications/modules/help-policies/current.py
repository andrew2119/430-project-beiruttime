"""Read-only guidance and exact accepted-policy retrieval."""
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

VERSION = "help-policies.v1"
OPERATIONS = {
    "guidance": ("GET", "/v1/help-policies", "public"),
    "accepted_terms": ("GET", "/v1/help-policies/accepted-terms/{record_id}", "current-record"),
}


@dataclass(frozen=True)
class Request:
    operation_id: str
    actor_id: str
    organization_id: str | None
    subject_id: str
    watch_id: str
    record_id: str
    expected_revision: int

    def __post_init__(self):
        values = (self.operation_id, self.actor_id, self.subject_id,
                  self.watch_id, self.record_id)
        if self.organization_id is not None:
            values += (self.organization_id,)
        if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", v) for v in values):
            raise ValueError("invalid_reference")
        if type(self.expected_revision) is not int or not 1 <= self.expected_revision <= 9_007_199_254_740_991:
            raise ValueError("invalid_revision")


@dataclass(frozen=True)
class Authority:
    allowed: bool
    revision: int
    access_revision: str


@dataclass(frozen=True)
class Artifact:
    binding: Request
    policy_revision: str
    accepted_at: str
    en: str
    ar: str
    available_until: str | None = None


class Provider(Protocol):
    async def authorize(self, request: Request) -> Authority: ...
    async def accepted_terms(self, request: Request) -> Artifact | None: ...


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("invalid_utc")
    return parsed.astimezone(timezone.utc)


def response(request: Request, state: str, revision=None, artifact=None):
    return {
        "schema_version": VERSION, **request.__dict__, "state": state,
        "revision": revision, "pending_reason": None if state == "ready" else state,
        "next_actor": None if state == "ready" else request.actor_id,
        "next_review_at": None, "artifact": artifact,
    }


async def read_accepted(request: Request, provider: Provider | None, now: datetime | Callable[[], datetime]):
    clock = now if callable(now) else lambda: now
    instant = clock()
    if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
        raise ValueError("invalid_utc")
    if provider is None:
        return response(request, "unavailable")
    try:
        async with asyncio.timeout(2):
            before = await provider.authorize(request)
            if not before.allowed:
                return response(request, "denied")
            if before.revision != request.expected_revision:
                return response(request, "stale", before.revision)
            artifact = await provider.accepted_terms(request)
            after = await provider.authorize(request)
            if not after.allowed or after.access_revision != before.access_revision:
                return response(request, "denied")
            if after.revision != request.expected_revision:
                return response(request, "stale", after.revision)
            if artifact is None:
                return response(request, "pending", after.revision)
            if artifact.binding != request:
                return response(request, "denied")
            instant = clock()
            if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
                raise ValueError("invalid_utc")
            accepted = utc(artifact.accepted_at)
            if accepted > instant or (artifact.available_until is not None and instant >= utc(artifact.available_until)):
                return response(request, "unavailable")
            if not artifact.policy_revision or len(artifact.policy_revision) > 128:
                return response(request, "unavailable")
            if any(not isinstance(v, str) or not v.strip() or len(v) > 100_000 for v in (artifact.en, artifact.ar)):
                return response(request, "unavailable")
            return response(request, "ready", after.revision, {
                "issuer": "E03", "policy_revision": artifact.policy_revision,
                "accepted_at": artifact.accepted_at, "en": artifact.en, "ar": artifact.ar,
            })
    except Exception:
        return response(request, "unavailable")
