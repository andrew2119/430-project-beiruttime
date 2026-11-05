"""CP B-04/B-09: one lock/transaction owns a saved command and its outbox."""

import hashlib
import json
from datetime import datetime
from bt_contracts_core.models import EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_events import enqueue


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def dto(row, *, public=False):
    result = {
        key: row[key]
        for key in (
            "id",
            "revision",
            "status",
            "seller_type",
            "seller_label",
            "physical_watch_id",
            "is_demo",
            "rules_version",
        )
    }
    result.update(
        facts=unpack(row["facts"]),
        photo_ids=[str(i) for i in row["photo_ids"]],
        cover_id=row["cover_id"],
        published_at=row["published_at"],
    )
    if not public:
        result.update(
            updated_at=row["updated_at"], fee_snapshot=unpack(row["fee_snapshot"]), is_hidden=row["is_hidden"]
        )
    else:
        result.update(seller_id=row["owner_subject_id"], organization_id=row["organization_id"])
    return json.loads(json.dumps(result, default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x)))


def command_key(request):
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 128 or not all(c.isalnum() or c in "-_:. " for c in key):
        raise PublicError("idempotency_required", "Supply a bounded Idempotency-Key.", status=400)
    return key


def revision(request):
    try:
        value = int(request.headers.get("If-Match", "").strip('"'))
    except ValueError:
        value = 0
    if value < 1:
        raise PublicError("revision_required", "Supply the current revision in If-Match.", status=428)
    return value


async def lock_listing(tx, listing_id, *, expected_revision=None):
    """Borrow the caller's unit of work; never commit or perform HTTP.

    Published edits and withdrawal projections share this source lock. Orders
    remains the sole physical-watch fence; acquire it outside this transaction.
    """
    await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"listing:{listing_id}")
    row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
    if row is None:
        raise PublicError("not_found", "Listing not found.", status=404)
    if expected_revision is not None:
        check_revision(row, expected_revision)
    return row


async def require_no_pending_edit(tx, listing_id, *, operation_id=None):
    if await tx.fetchval("SELECT to_regclass('catalog_listing_edits')"):
        pending = await tx.fetchval(
            "SELECT id FROM catalog_listing_edits WHERE listing_id=$1 AND status IN ('pending','committed')", listing_id
        )
        if pending is not None and pending != operation_id:
            raise PublicError(
                "edit_pending", "Reconcile the current listing edit before another source mutation.", status=409
            )


def check_revision(row, expected):
    if row["revision"] != expected:
        raise PublicError("stale_revision", "This listing changed. Reload before saving.", status=409)


async def replay(tx, scope, key, payload):
    previous = await tx.fetchrow(
        "SELECT digest,response FROM catalog_commands WHERE scope=$1 AND operation_key=$2", scope, key
    )
    if previous:
        if previous["digest"] != digest(payload):
            raise PublicError("idempotency_conflict", "This operation key belongs to a different request.", status=409)
        return unpack(previous["response"])


async def remember(tx, scope, key, payload, response):
    await tx.execute(
        "INSERT INTO catalog_commands(scope,operation_key,digest,response) VALUES($1,$2,$3,$4::jsonb)",
        scope,
        key,
        digest(payload),
        json.dumps(response, default=str),
    )


async def emit(tx, request, row, kind):
    # Closed references only: private documents and watch serials never enter events.
    event = EventEnvelope(
        type=f"catalog.listing.{kind}.v1",
        source="catalog",
        subject=str(row["id"]),
        request_id=request.state.request_id,
        data={
            "listing_id": str(row["id"]),
            "revision": row["revision"],
            "seller_id": str(row["owner_subject_id"]),
            "organization_id": str(row["organization_id"]) if row["organization_id"] else None,
            "status": row["status"],
            "is_demo": row["is_demo"],
        },
    )
    await enqueue(
        tx,
        event,
        # A new event never enters the legacy receiver's closed allowlist.
        # Its versioned destination is enabled only after a receiver handoff.
        (["communications-seller-workspace-v2"] if kind == "revised" else ["communications-seller-workspace"])
        + (["auction"] if kind == "published" and unpack(row["facts"])["sale_mode"] == "auction" else []),
    )
