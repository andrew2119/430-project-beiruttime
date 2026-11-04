import os
from uuid import UUID, uuid4
from fastapi import APIRouter, Request, Query
from bt_contracts.catalog.listings.v1 import CreateDraft, SaveDraft
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from .dependencies import principal, seller_scope, assert_owner, upstream
from .repository import dto, command_key, revision, check_revision, replay, remember, emit

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






