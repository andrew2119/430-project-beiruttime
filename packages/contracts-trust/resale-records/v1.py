"""Versioned private transfer boundary. Provider facts are never client input."""
from dataclasses import dataclass

VERSION = 'resale-records.v1'

@dataclass(frozen=True)
class Command:
    operation_id: str
    actor_id: str
    organization_id: str
    subject_id: str
    watch_id: str
    sale_id: str
    expected_revision: int
    source_revision: int
    quote_revision: int
    policy_revision: int

@dataclass(frozen=True)
class Facts:
    actor_id: str
    organization_id: str
    subject_id: str
    watch_id: str
    sale_id: str
    revision: int
    source_revision: int
    quote_revision: int
    policy_revision: int
    current_authority: bool
    seller_owns_record: bool
    recipient_authorized: bool
    released: bool
    prior_signature_valid: bool
    independent_pass: bool
    actual_custody: bool
    commitment_matches: bool
    prior_hash: str
    issuer: str
    inspected_at: str
    released_at: str
    scope: str
    public_watch_reference: str
    inspected_watch_revision: int
    current_watch_revision: int
    inspection_valid_until: str

@dataclass(frozen=True)
class Access:
    actor_id: str
    organization_id: str
    subject_id: str
    watch_id: str
    allowed: bool
