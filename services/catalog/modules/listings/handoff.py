"""Identity's signed handoff to Catalog's deploy demo seed.

Identity's seed sends one `identity.demo-seed.handoff.v1` event per set and holder, through its own outbox
and relay, on every seed run: 'ready' while its record proves, on rows it has locked, that holder's account (and,
for staff, the staff's own sample business, membership and grant) is still the very row it inserted and active,
else 'withdrawn'; its removal withdraws all four. Each carries Identity's order for that holder (seq) and an
assertion: an RS256 signature, with the seed's own handoff key pair, over exactly the event id, the order, the
fields and the issue time. Only Identity's seed holds the private half; Catalog holds only the public half
(BT_DEMO_SEED_HANDOFF_PUBLIC_KEY), and neither is any service or event key, so neither Catalog's runtime role
nor its service signing key can make one.

The event ingress has already checked Identity's service signature, the audience and that the event's source is
Identity. Here a handoff is refused (422) unless it names one of the four pinned set, holder, account and business
tuples and its assertion verifies; it is refused (409, retried by Identity's relay) while Catalog's seed switch is
off or its handoff key is missing or wrongly set. An accepted one is stored only by `demo_seed_receive()`, which
runs as the migration owner, under the seed's shared lock and the holder's own lock (409 while either is busy),
only in the ingress transaction that wrote its inbox entry. It moves the holder's mark to the newest order it has
received, never back, and records the receipt and that entry in `demo_seed_rows`, so removal deletes exactly those.
The runtime role may read receipts and marks but never insert, edit or delete one.

The seed admits a sample draft, or attaches its photo, only under the holder's lock, held to commit, and only
from the one receipt the holder's mark names (`admitted()`): recorded with its incarnation, its assertion verified
again here against the stored fields with this process's key, ready, naming exactly the account and business the
draft would be owned by, and issued at most HANDOFF_FRESH_SECONDS ago. Anything else refuses, and an older receipt
never stands in for the newest one.
"""

from typing import Literal
from uuid import UUID
import asyncpg
from pydantic import Field, ValidationError
from bt_contracts_core.models import Contract
from bt_contracts_core.errors import PublicError
from bt_runtime import demo_seed

# Why admitted() refuses, in the order it checks.
REASONS = ("busy", "unkeyed", "waiting", "invalid", "mismatched", "withdrawn", "stale")


class Handoff(Contract):
    sample_set: Literal["demo", "click-test"]
    holder: Literal["seller", "staff"]
    subject_id: UUID
    business_id: UUID | None
    state: Literal["ready", "withdrawn"]
    seq: int = Field(strict=True, gt=0, lt=2**63)
    assertion: str = Field(min_length=1, max_length=demo_seed.HANDOFF_ASSERTION_LIMIT)


def invalid() -> PublicError:
    return PublicError("invalid_event", "Invalid demo seed handoff.", status=422)


def fields(handoff) -> dict:
    """A handoff's signed fields, as Identity's handoff_data() writes them."""
    return {
        "sample_set": handoff["sample_set"],
        "holder": handoff["holder"],
        "subject_id": str(handoff["subject_id"]),
        "business_id": None if handoff["business_id"] is None else str(handoff["business_id"]),
        "state": handoff["state"],
    }


async def receive(tx, event):
    if not demo_seed.enabled():
        raise PublicError("demo_seed_off", "The demo seed is not on in Catalog.", status=409)
    try:
        key = demo_seed.handoff_verifying_key()
    except demo_seed.HandoffKey:
        raise PublicError("demo_seed_unkeyed", "The demo seed handoff key is not set in Catalog.", status=409) from None
    try:
        handoff = Handoff.model_validate(event.data)
    except ValidationError:
        raise invalid() from None
    if (
        (handoff.subject_id, handoff.business_id) != demo_seed.handoff_ids(handoff.sample_set, handoff.holder)
        or event.subject != str(handoff.subject_id)
        or event.request_id != demo_seed.REQUEST_ID
        or not demo_seed.verify_handoff(
            key, handoff.assertion, event.id, handoff.seq, fields(handoff.model_dump()), event.time)
    ):
        raise invalid()
    try:
        await tx.execute(
            "SELECT demo_seed_receive($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            event.id,
            handoff.sample_set,
            handoff.holder,
            handoff.subject_id,
            handoff.business_id,
            handoff.state,
            event.time,
            handoff.seq,
            handoff.assertion,
        )
    except asyncpg.LockNotAvailableError:
        raise PublicError("demo_seed_busy", "The demo seed is busy in Catalog.", status=409) from None
    except asyncpg.InvalidParameterValueError:
        raise invalid() from None


async def admitted(tx, sample_set: str, holder: str) -> str | None:
    """None when the receipt this holder's mark names is Identity's, ready, fresh and names exactly the expected
    account and business; otherwise why not, one of REASONS. It first takes the holder's lock without waiting
    ('busy' when a receipt or another step holds it) and keeps it to commit, so no receipt can change between
    this check and the caller's write."""
    if not await tx.fetchval(
        "SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))", demo_seed.holder_lock(sample_set, holder)
    ):
        return "busy"
    try:
        key = demo_seed.handoff_verifying_key()
    except demo_seed.HandoffKey:
        return "unkeyed"
    mark = await tx.fetchrow(
        "SELECT seq, event_id FROM demo_seed_handoff_marks WHERE sample_set=$1 AND holder=$2", sample_set, holder
    )
    if mark is None:
        return "waiting"
    latest = await tx.fetchrow(
        f"""SELECT t.event_id, t.sample_set, t.holder, t.subject_id, t.business_id, t.state, t.seq, t.issued_at,
        t.assertion,
        t.issued_at < now() - $6 * interval '1 second' OR t.issued_at > now() + $7 * interval '1 second' AS stale
        FROM demo_seed_handoffs AS t JOIN {demo_seed.LEDGER} AS r ON r.table_name='demo_seed_handoffs'
        AND r.row_key=jsonb_build_object('event_id', t.event_id::text) AND r.demo_key=$3
        AND r.born = {await demo_seed.born(tx, "demo_seed_handoffs")}
        WHERE t.sample_set=$1 AND t.holder=$2 AND t.seq=$4 AND t.event_id=$5""",
        sample_set,
        holder,
        demo_seed.handoff_key(sample_set, holder),
        mark["seq"],
        mark["event_id"],
        demo_seed.HANDOFF_FRESH_SECONDS,
        demo_seed.HANDOFF_SKEW_SECONDS,
    )
    if latest is None or not demo_seed.verify_handoff(
        key, latest["assertion"], latest["event_id"], latest["seq"], fields(latest), latest["issued_at"]
    ):
        return "invalid"
    if (latest["subject_id"], latest["business_id"]) != demo_seed.handoff_ids(sample_set, holder):
        return "mismatched"
    if latest["state"] != "ready":
        return "withdrawn"
    return "stale" if latest["stale"] else None
