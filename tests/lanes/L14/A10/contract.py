"""Versioned preparation contract; observations are never transaction authority."""
from dataclasses import dataclass
from typing import Protocol

VERSION = 'auction-recovery-proof.v1'
OPERATIONS = {
    'bid': 'POST /v1/auctions/{auction_id}/bids',
    'maximum': 'POST /v1/auctions/{auction_id}/maximum',
    'lookup': 'GET /v1/auction-operations/by-key/{key}',
    'snapshot': 'GET /v2/auctions/{auction_id}',
    'replay': 'GET /v2/auctions/{auction_id}/history?after_sequence={sequence}&limit=100',
}
# Each case runs on fresh synthetic stock, with current scope and retained terms.
CASES = (
    'stale_revision', 'denied_scope', 'revoked_identity', 'cross_account_lookup',
    'timeout_pending', 'lost_response_same_operation', 'duplicate_command',
    'replica_loss_poll_resync', 'worker_restart_acknowledged_bids',
    'outbox_replay_duplicate_notice', 'one_winner_allocation_restart',
    'before_end', 'equal_end', 'after_end', 'private_maximum_redaction',
)
EXPECTED = {
    'stale_revision': 'denied', 'denied_scope': 'denied',
    'revoked_identity': 'denied', 'cross_account_lookup': 'denied',
    'timeout_pending': 'pending', 'equal_end': 'denied', 'after_end': 'denied',
}


@dataclass(frozen=True)
class CommandBinding:
    """Retain these privately across retries; never include them in reports."""
    operation_id: str
    actor_id: str
    organization_id: str | None
    subject_id: str
    watch_id: str
    expected_revision: int
    quote_id: str
    quote_revision: int
    policy_revision: str


@dataclass(frozen=True)
class Dataset:
    viewers: int = 50
    bidders: int = 200
    replicas: int = 2
    timeout_seconds: int = 60
    request_timeout_seconds: int = 5
    max_attempts: int = 3
    history_page_size: int = 100
    currency: str = 'USD'
    opening_minor: int = 400000
    increment_minor: int = 10000


@dataclass(frozen=True)
class Sample:
    participant: int
    replica: int
    sequence: int
    elapsed_ms: float
    error: bool = False


@dataclass(frozen=True)
class CaseResult:
    state: str
    invariants: tuple[str, ...]


# Assertions must be established from observed durable reads, never seeded flags.
INVARIANTS = {
    'lost_response_same_operation': ('same_operation', 'one_public_change'),
    'duplicate_command': ('same_operation', 'one_public_change'),
    'replica_loss_poll_resync': ('bounded_resync', 'ordered_gap_free', 'same_snapshot'),
    'worker_restart_acknowledged_bids': ('all_acknowledged_retained', 'same_sequence'),
    'outbox_replay_duplicate_notice': ('one_notice_per_recipient_event', 'durable_inbox'),
    'one_winner_allocation_restart': ('one_winner', 'one_order', 'same_watch_commitment'),
    'before_end': ('accepted_before_end', 'unchanged_scheduled_end'),
    'private_maximum_redaction': ('no_private_fields', 'full_step_v2'),
}


class Provider(Protocol):
    """Separate-machine adapter. No credentials or private bodies enter results.

    run_load must issue concurrent requests to both independent local replicas
    sharing one durable store, not two in-memory copies. Viewer samples measure
    admission-to-render/read visibility for EVERY viewer on BOTH replicas after
    a real accepted bid. Bidder samples cover 200 distinct authorized buyers in
    a separate run. Receipt order is canonical admission sequence, not client
    dispatch time. Each request is bounded by Dataset, including retries/pages.
    exercise must assert the named invariants from actual source reads and raise
    on failure. timeout_pending must not invent success or issue a fresh key.
    """

    async def run_load(self, kind: str, dataset: Dataset) -> list[Sample]: ...

    async def exercise(self, case: str, dataset: Dataset) -> CaseResult: ...
