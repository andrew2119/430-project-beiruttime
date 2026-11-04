import json
import os
from uuid import UUID, uuid4
from fastapi import APIRouter, Request, Query
from bt_contracts.catalog.listings.v1 import CreateDraft, SaveDraft, Publish, WatchFacts, incomplete
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from .dependencies import principal, seller_scope, assert_owner, upstream, service_request
from .repository import dto, unpack, command_key, revision, check_revision, replay, remember, emit
from .quotes import publication_quote

router = APIRouter()


@router.post("/v1/seller/listings", status_code=201)
async def create(body: CreateDraft, request: Request):
    person = await principal(request)
    kind = seller_scope(person)
    if body.demo_key:
        if os.getenv("BT_ENVIRONMENT") != "demo":
            raise AccessDenied("Demo import is not enabled for this environment")
        seller_scope(person, "identity.listings.publish")
    label = ("Demonstration " if body.demo_key else "") + "private seller"
    if person.actor.organization_id:
        business = await upstream(request, "identity", "GET", f"/v1/businesses/{person.actor.organization_id}")
        if (
            not isinstance(business, dict)
            or business.get("id") != str(person.actor.organization_id)
            or business.get("kind") not in ("dealer", "brand")
            or not isinstance(business.get("capabilities"), list)
            or not isinstance(business.get("public_name"), str)
            or not business["public_name"].strip()
        ):
            raise PublicError(
                "identity_unavailable", "Official business details are temporarily unavailable.", status=503
            )
        if (
            business.get("state") != "active"
            or business.get("platform_onboarded") is not True
            or business.get("authenticated_business") is not True
            or "sales" not in business.get("capabilities", [])
        ):
            raise AccessDenied("An active official sales business is required")
        kind = business["kind"]
        label = ("Demonstration " if body.demo_key or business.get("sample") else "") + str(
            business.get("public_name") or kind
        )[:160]
    key = command_key(request)
    scope = f"create:{person.actor.subject_id}:{person.actor.organization_id}"
    payload = body.model_dump(mode="json")
    async with unit_of_work(request.app.state.pool, lock_key=scope) as tx:
        previous = await replay(tx, scope, key, payload)
        if previous is not None:
            return previous
        if body.demo_key and await tx.fetchval("SELECT id FROM catalog_listings WHERE demo_key=$1", body.demo_key):
            raise PublicError("demo_exists", "This demonstration record already exists.", status=409)
        row = await tx.fetchrow(
            """INSERT INTO catalog_listings(id,owner_subject_id,organization_id,seller_type,seller_label,
            physical_watch_id,facts,is_demo,demo_key) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9) RETURNING *""",
            uuid4(),
            person.actor.subject_id,
            person.actor.organization_id,
            kind,
            label,
            uuid4(),
            body.facts.model_dump_json(),
            bool(body.demo_key),
            body.demo_key,
        )
        await emit(tx, request, row, "draft-saved")
        answer = dto(row)
        await remember(tx, scope, key, payload, answer)
        return answer


@router.get("/v1/seller/listings")
async def own(request: Request, limit: int = Query(30, ge=1, le=50), before: UUID | None = None):
    person = await principal(request)
    seller_scope(person)
    async with request.app.state.pool.acquire() as tx:
        async with tx.transaction(isolation="repeatable_read", readonly=True):
            rows = await tx.fetch(
                """SELECT * FROM catalog_listings WHERE
              (($2::uuid IS NULL AND owner_subject_id=$1 AND organization_id IS NULL) OR organization_id=$2)
              AND ($3::uuid IS NULL OR id < $3) ORDER BY id DESC LIMIT $4""",
                person.actor.subject_id,
                person.actor.organization_id,
                before,
                limit + 1,
            )
            counts = await tx.fetchrow(
                """SELECT count(*) FILTER(WHERE status='draft') AS draft,
              count(*) FILTER(WHERE status='published') AS published,
              count(*) FILTER(WHERE status='publication_pending') AS publication_pending
              FROM catalog_listings WHERE (($2::uuid IS NULL AND owner_subject_id=$1 AND organization_id IS NULL) OR organization_id=$2)""",
                person.actor.subject_id,
                person.actor.organization_id,
            )
    return {
        "items": [dto(row) for row in rows[:limit]],
        "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
        "counts": dict(counts),
    }


@router.get("/v1/seller/listings/{listing_id}")
async def get_owned(listing_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing_id)
    assert_owner(row, person)
    return dto(row)


@router.put("/v1/seller/listings/{listing_id}")
async def save(listing_id: UUID, body: SaveDraft, request: Request):
    person = await principal(request)
    seller_scope(person)
    expected = revision(request)
    key = command_key(request)
    scope = f"save:{listing_id}:{person.actor.subject_id}"
    payload = {"revision": expected, **body.model_dump(mode="json")}
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{listing_id}") as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
        assert_owner(row, person)
        previous = await replay(tx, scope, key, payload)
        if previous is not None:
            return previous
        check_revision(row, expected)
        if row["status"] != "draft":
            raise PublicError("listing_frozen", "Only a draft can be edited.", status=409)
        row = await tx.fetchrow(
            "UPDATE catalog_listings SET facts=$2::jsonb,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
            listing_id,
            body.facts.model_dump_json(),
        )
        await emit(tx, request, row, "draft-saved")
        answer = dto(row)
        await remember(tx, scope, key, payload, answer)
        return answer


@router.post("/v1/seller/listings/{listing_id}/publish")
async def publish(listing_id: UUID, body: Publish, request: Request):
    person = await principal(request)
    seller_scope(person, "identity.listings.publish")
    expected = revision(request)
    key = command_key(request)
    scope = f"publish:{listing_id}:{person.actor.subject_id}"
    payload = {"revision": expected, **body.model_dump(mode="json")}
    async with request.app.state.pool.acquire() as tx:
        preview = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing_id)
    assert_owner(preview, person)
    if preview["is_hidden"]:
        raise PublicError("listing_moderated", "This listing is not currently eligible for publication.", status=403)
    # An invalid quote must not strand an otherwise editable draft. A prepared
    # operation retains its accepted snapshot while retrying an ambiguous fence.
    quote = unpack(preview["fee_snapshot"]) if preview["status"] != "draft" else None
    if quote is None:
        # Report incomplete facts before consulting an optional quote reference.
        missing = incomplete(WatchFacts.model_validate(unpack(preview["facts"])), len(preview["photo_ids"]))
        if missing:
            raise PublicError(
                "listing_incomplete",
                "Complete the highlighted steps before publishing.",
                status=422,
                details={"fields": missing},
            )
        quote = await upstream(request, "pricing", "GET", f"/v1/quotes/{body.fee_quote_id}")
    # Freeze first, release SQL locks before remote work. Retrying resumes the SAME
    # Orders registration identity; ambiguous upstream results can never free a fence.
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{listing_id}") as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
        assert_owner(row, person)
        previous = await replay(tx, scope, key, payload)
        if previous is not None:
            return previous
        operation = await tx.fetchrow("SELECT * FROM catalog_publications WHERE listing_id=$1", listing_id)
        if operation:
            if unpack(operation["request"]) != body.model_dump(mode="json") or operation["base_revision"] != expected:
                raise PublicError("publication_in_progress", "Resume the original publication request.", status=409)
            if row["status"] == "published":
                return dto(row)
            # A durable prepared decision keeps its original accepted terms when
            # an ambiguous Orders result is retried, without extending a quote.
            quote = publication_quote(
                unpack(row["fee_snapshot"]),
                body=body,
                row=row,
                owner_id=operation["actor_id"],
                accepted_at=operation["created_at"],
            )
        else:
            check_revision(row, expected)
            facts = WatchFacts.model_validate(unpack(row["facts"]))
            missing = incomplete(facts, len(row["photo_ids"]))
            if missing:
                raise PublicError(
                    "listing_incomplete",
                    "Complete the highlighted steps before publishing.",
                    status=422,
                    details={"fields": missing},
                )
            if row["status"] != "draft":
                raise PublicError("listing_frozen", "Listing cannot be published.", status=409)
            quote = publication_quote(
                quote,
                body=body,
                row=row,
                owner_id=person.actor.subject_id,
                accepted_at=await tx.fetchval("SELECT clock_timestamp()"),
            )
            operation = await tx.fetchrow(
                """INSERT INTO catalog_publications(id,listing_id,actor_id,base_revision,request)
                VALUES($1,$2,$3,$4,$5::jsonb) RETURNING *""",
                uuid4(),
                listing_id,
                person.actor.subject_id,
                expected,
                body.model_dump_json(),
            )
            row = await tx.fetchrow(
                "UPDATE catalog_listings SET status='publication_pending',fee_snapshot=$2::jsonb,rules_version=$3,updated_at=now() WHERE id=$1 RETURNING *",
                listing_id,
                json.dumps(quote),
                body.rules_version,
            )
    facts = unpack(row["facts"])
    sale_mode = {"fixed_price": "fixed", "auction": "auction", "offer": "seller_base"}[facts["sale_mode"]]
    registration = await service_request(
        request,
        "orders",
        "POST",
        "/internal/v1/watches/register",
        headers={"Idempotency-Key": str(operation["id"])},
        json={
            "watch_id": str(row["physical_watch_id"]),
            "listing_id": str(listing_id),
            "listing_revision": expected + 1,
            "sale_mode": sale_mode,
            "is_demo": row["is_demo"],
            "seller_id": str(row["owner_subject_id"]),
            "organization_id": str(row["organization_id"]) if row["organization_id"] else None,
        },
    )
    if (
        registration.get("status") != "available"
        or registration.get("watch_id") != str(row["physical_watch_id"])
        or registration.get("listing_id") != str(listing_id)
        or registration.get("sale_mode") != sale_mode
        or type(registration.get("revision")) is not int
        or registration["revision"] < 1
    ):
        raise PublicError(
            "registration_pending", "Physical watch registration is not confirmed. Retry this operation.", status=503
        )
    # Keep only the immutable registration proof, never buyer data or a stale
    # availability status. Current availability always belongs to Orders.
    registration = {name: registration[name] for name in ("watch_id", "listing_id", "sale_mode", "revision")}
    # Refresh authorization after the network gap, before making a public projection.
    person = await principal(request)
    seller_scope(person, "identity.listings.publish")
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{listing_id}") as tx:
        current = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
        assert_owner(current, person)
        if current["is_hidden"]:
            raise PublicError(
                "listing_moderated", "This listing is not currently eligible for publication.", status=403
            )
        if current["status"] == "published":
            return dto(current)
        if current["revision"] != expected or current["status"] != "publication_pending":
            raise PublicError("stale_revision", "The listing revision changed.", status=409)
        row = await tx.fetchrow(
            """UPDATE catalog_listings SET status='published',revision=revision+1,published_at=now(),updated_at=now(),
            registration=$2::jsonb,fee_snapshot=$3::jsonb,rules_version=$4 WHERE id=$1 RETURNING *""",
            listing_id,
            json.dumps(registration),
            json.dumps(quote),
            body.rules_version,
        )
        await tx.execute("UPDATE catalog_publications SET status='succeeded' WHERE listing_id=$1", listing_id)
        await emit(tx, request, row, "published")
        answer = dto(row)
        await remember(tx, scope, key, payload, answer)
        return answer


@router.get("/v1/listings/{listing_id}/report-subject")
async def report_subject(listing_id: UUID, request: Request):
    person = await principal(request)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 AND status='published'", listing_id)
    if row is None:
        raise PublicError("not_found", "Listing not found.", status=404)
    if row["is_hidden"]:
        owner = (
            row["organization_id"] is None
            and person.actor.organization_id is None
            and row["owner_subject_id"] == person.actor.subject_id
        )
        if row["organization_id"] == person.actor.organization_id and row["organization_id"] is not None:
            seller_scope(person, "identity.listings.publish")
            owner = True
        if not owner:
            orders = await upstream(request, "orders", "GET", "/v1/orders")
            records = orders.get("items") if isinstance(orders, dict) else None
            if not isinstance(records, list):
                raise PublicError(
                    "orders_unavailable", "Transaction participation is temporarily unavailable.", status=503
                )
            party = person.actor.organization_id is None and any(
                isinstance(item, dict)
                and item.get("watch_id") == str(row["physical_watch_id"])
                and item.get("buyer_id") == str(person.actor.subject_id)
                for item in records
            )
            if not party:
                raise AccessDenied("Hidden listing is limited to its current transaction parties")
    return {
        "id": str(row["id"]),
        "seller_id": str(row["owner_subject_id"]),
        "organization_id": str(row["organization_id"]) if row["organization_id"] else None,
    }


@router.get("/v1/listings/{listing_id}/publication")
async def publication(listing_id: UUID, request: Request):
    # A minimal public, canonical publication proof for downstream sale commands.
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow(
            "SELECT * FROM catalog_listings WHERE id=$1 AND status='published' AND NOT is_hidden", listing_id
        )
    if row is None:
        raise PublicError("not_found", "Listing not found.", status=404)
    return dto(row, public=True)
