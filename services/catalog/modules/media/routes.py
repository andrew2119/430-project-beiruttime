import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import APIRouter, Request
from fastapi.responses import Response
from bt_contracts.catalog.listings.v1 import Gallery
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work
from service_app.catalog_dependencies import principal, seller_scope, assert_owner
from modules.listings.repository import dto, revision, command_key, check_revision, replay, remember, emit
from .images import normalize, MAX_BYTES, attribution_matches, embed_attribution

router = APIRouter()


def credit_projection(raw):
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        return None
    fields = (
        "title",
        "author",
        "author_url",
        "source_url",
        "license",
        "license_url",
        "changes",
        "credit",
        "alt_en",
        "alt_ar",
        "share_alike_required",
    )
    return {field: value.get(field) for field in fields}


DECODERS = asyncio.Semaphore(1)


async def decode(content):
    if DECODERS.locked():
        raise PublicError("media_busy", "Image processing is busy. Retry shortly.", status=503)
    await DECODERS.acquire()
    task = asyncio.create_task(asyncio.to_thread(normalize, content))

    # Cancellation does not stop a native decoder. Keep its slot until the actual
    # thread finishes, rather than admitting unlimited abandoned image work.
    def completed(done):
        DECODERS.release()
        if not done.cancelled():
            done.exception()

    task.add_done_callback(completed)
    return await asyncio.shield(task)


async def read_bytes(request):
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise PublicError("media_bytes_limit", "File exceeds the upload budget.", status=413)
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise PublicError("empty_media", "Select a file to upload.", status=422)
    return content


@router.post("/v1/seller/listings/{listing_id}/media", status_code=201)
async def upload(listing_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    expected = revision(request)
    key = command_key(request)
    kind = request.query_params.get("kind", request.headers.get("X-Media-Kind", ""))
    if kind not in ("public_photo", "private_document"):
        raise PublicError("invalid_media_kind", "Choose a public photograph or private document.", status=422)
    # Authorize before reading or decoding the bytes.
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing_id)
    assert_owner(row, person)
    content = await read_bytes(request)
    source_size = len(content)
    source_hash = hashlib.sha256(content).hexdigest()
    variants = None
    mime = "application/octet-stream"
    if kind == "public_photo":
        if request.query_params.get("public_safe", request.headers.get("X-Public-Safe")) != "true":
            raise PublicError(
                "safe_photo_required",
                "Public photos must contain only a safe watch view, not identity, ownership or full-serial evidence.",
                status=422,
            )
        variants = await decode(content)
        mime = "image/jpeg"
    elif content.startswith(b"%PDF-"):
        mime = "application/pdf"
    else:
        # Private images are normalized too, but never given public variants.
        private = await decode(content)
        content = private["detail"]["content"]
        mime = "image/jpeg"
    credit = None
    demo_asset = request.query_params.get("demo_asset", request.headers.get("X-Demo-Asset"))
    if demo_asset:
        if kind != "public_photo" or not row["is_demo"] or os.getenv("BT_ENVIRONMENT") != "demo":
            raise PublicError("demo_asset_denied", "Demonstration asset binding is not permitted.", status=403)
        seller_scope(person, "identity.listings.publish")
        manifest_path = Path(os.getenv("BT_DEMO_MANIFEST", "/app/demo/images-manifest.json"))
        manifest = json.loads(manifest_path.read_text())
        credit = next((a for a in manifest["assets"] if a["id"] == demo_asset), None)
        if (
            not credit
            or not credit.get("license_url")
            or credit.get("local_sha256") != source_hash
            or not attribution_matches(content, credit)
        ):
            raise PublicError(
                "demo_asset_invalid",
                "Demonstration asset license/hash does not match.",
                status=422,
                details={"asset": demo_asset},
            )
        if variants:
            embed_attribution(variants, credit)
    scope = f"media:{listing_id}:{person.actor.subject_id}"
    payload = {
        "revision": expected,
        "kind": kind,
        "sha256": source_hash,
        "demo_asset": demo_asset,
    }
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{listing_id}") as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
        assert_owner(row, person)
        previous = await replay(tx, scope, key, payload)
        if previous is not None:
            return previous
        check_revision(row, expected)
        if row["status"] != "draft":
            raise PublicError("listing_frozen", "Only a draft can change media.", status=409)
        count = await tx.fetchval(
            "SELECT count(*) FROM catalog_media WHERE listing_id=$1 AND kind=$2", listing_id, kind
        )
        total = await tx.fetchval(
            "SELECT coalesce(sum(source_bytes),0) FROM catalog_media WHERE listing_id=$1", listing_id
        )
        if count >= (12 if kind == "public_photo" else 5) or total + source_size > 40_000_000:
            raise PublicError(
                "media_aggregate_limit", "This listing reached its file count or aggregate byte budget.", status=413
            )
        asset = uuid4()
        detail = variants["detail"] if variants else None
        await tx.execute(
            """INSERT INTO catalog_media(id,listing_id,kind,content_hash,source_bytes,mime,width,height,credit,private_bytes)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)""",
            asset,
            listing_id,
            kind,
            payload["sha256"],
            source_size,
            mime,
            detail["width"] if detail else None,
            detail["height"] if detail else None,
            json.dumps(credit) if credit else None,
            content if kind == "private_document" else None,
        )
        if variants:
            await tx.executemany(
                "INSERT INTO catalog_media_variants(media_id,variant,width,height,content) VALUES($1,$2,$3,$4,$5)",
                [(asset, name, value["width"], value["height"], value["content"]) for name, value in variants.items()],
            )
            row = await tx.fetchrow(
                """UPDATE catalog_listings SET photo_ids=array_append(photo_ids,$2),cover_id=coalesce(cover_id,$2),
                revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *""",
                listing_id,
                asset,
            )
        else:
            row = await tx.fetchrow(
                "UPDATE catalog_listings SET revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *", listing_id
            )
        await emit(tx, request, row, "media-updated")
        answer = {"asset_id": str(asset), "kind": kind, "listing": dto(row)}
        await remember(tx, scope, key, payload, answer)
        return answer


@router.put("/v1/seller/listings/{listing_id}/gallery")
async def gallery(listing_id: UUID, body: Gallery, request: Request):
    person = await principal(request)
    seller_scope(person)
    expected = revision(request)
    key = command_key(request)
    scope = f"gallery:{listing_id}:{person.actor.subject_id}"
    payload = {"revision": expected, **body.model_dump(mode="json")}
    if len(set(body.photo_ids)) != len(body.photo_ids) or body.cover_id not in body.photo_ids:
        raise PublicError("invalid_gallery", "Choose unique photographs and a cover from this gallery.", status=422)
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{listing_id}") as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
        assert_owner(row, person)
        previous = await replay(tx, scope, key, payload)
        if previous is not None:
            return previous
        check_revision(row, expected)
        if row["status"] != "draft":
            raise PublicError("listing_frozen", "Only a draft can change media.", status=409)
        photos = await tx.fetchval(
            "SELECT count(*) FROM catalog_media WHERE listing_id=$1 AND kind='public_photo' AND id=ANY($2::uuid[])",
            listing_id,
            body.photo_ids,
        )
        if photos != len(body.photo_ids):
            raise PublicError(
                "gallery_scope_denied", "Only public photographs of this listing can enter its gallery.", status=403
            )
        row = await tx.fetchrow(
            "UPDATE catalog_listings SET photo_ids=$2,cover_id=$3,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
            listing_id,
            body.photo_ids,
            body.cover_id,
        )
        await emit(tx, request, row, "media-updated")
        answer = dto(row)
        await remember(tx, scope, key, payload, answer)
        return answer


@router.delete("/v1/seller/listings/{listing_id}/media/{asset_id}")
async def remove_media(listing_id: UUID, asset_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    expected = revision(request)
    key = command_key(request)
    scope = f"media-delete:{listing_id}:{person.actor.subject_id}"
    payload = {"revision": expected, "asset_id": str(asset_id)}
    async with unit_of_work(request.app.state.pool, lock_key=f"listing:{listing_id}") as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1 FOR UPDATE", listing_id)
        assert_owner(row, person)
        previous = await replay(tx, scope, key, payload)
        if previous is not None:
            return previous
        check_revision(row, expected)
        if row["status"] != "draft":
            raise PublicError("listing_frozen", "Only a draft can change media.", status=409)
        asset = await tx.fetchrow("SELECT id FROM catalog_media WHERE id=$1 AND listing_id=$2", asset_id, listing_id)
        if asset is None:
            raise PublicError("not_found", "File not found.", status=404)
        photos = [value for value in row["photo_ids"] if value != asset_id]
        cover = row["cover_id"] if row["cover_id"] != asset_id else (photos[0] if photos else None)
        await tx.execute("DELETE FROM catalog_media WHERE id=$1 AND listing_id=$2", asset_id, listing_id)
        row = await tx.fetchrow(
            """UPDATE catalog_listings SET photo_ids=$2,cover_id=$3,revision=revision+1,updated_at=now()
            WHERE id=$1 RETURNING *""",
            listing_id,
            photos,
            cover,
        )
        await emit(tx, request, row, "media-updated")
        answer = dto(row)
        await remember(tx, scope, key, payload, answer)
        return answer


@router.get("/v1/seller/listings/{listing_id}/media")
async def media_list(listing_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing_id)
        assert_owner(row, person)
        items = await tx.fetch(
            "SELECT id,kind,mime,width,height,credit FROM catalog_media WHERE listing_id=$1 ORDER BY created_at,id",
            listing_id,
        )
    return {"items": [{**dict(i), "credit": credit_projection(i["credit"])} for i in items]}


@router.get("/v1/seller/listings/{listing_id}/media/{asset_id}")
async def private_media(listing_id: UUID, asset_id: UUID, request: Request):
    person = await principal(request)
    seller_scope(person)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow("SELECT * FROM catalog_listings WHERE id=$1", listing_id)
        assert_owner(row, person)
        # The owner decision precedes fetching private bytes.
        asset = await tx.fetchrow(
            "SELECT kind,mime,private_bytes FROM catalog_media WHERE id=$1 AND listing_id=$2", asset_id, listing_id
        )
        if not asset:
            raise PublicError("not_found", "File not found.", status=404)
        content = (
            asset["private_bytes"]
            if asset["kind"] == "private_document"
            else await tx.fetchval(
                "SELECT content FROM catalog_media_variants WHERE media_id=$1 AND variant='card'", asset_id
            )
        )
    return Response(
        content,
        media_type=asset["mime"],
        headers={
            "Content-Disposition": 'attachment; filename="watch-evidence"',
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/v1/listings/{listing_id}/photos/{asset_id}/{variant}")
async def public_photo(listing_id: UUID, asset_id: UUID, variant: str, request: Request):
    if variant not in ("thumb", "card", "detail"):
        raise PublicError("not_found", "Photo not found.", status=404)
    async with request.app.state.pool.acquire() as tx:
        asset = await tx.fetchrow(
            """SELECT v.content,m.credit FROM catalog_media_variants v JOIN catalog_media m ON m.id=v.media_id
            JOIN catalog_listings l ON l.id=m.listing_id WHERE l.id=$1 AND m.id=$2 AND v.variant=$3
            AND l.status='published' AND NOT l.is_hidden AND m.kind='public_photo' AND m.id=ANY(l.photo_ids)""",
            listing_id,
            asset_id,
            variant,
        )
    if not asset:
        raise PublicError("not_found", "Photo not found.", status=404)
    headers = {"Cache-Control": "no-store"}
    credit = json.loads(asset["credit"]) if isinstance(asset["credit"], str) else asset["credit"]
    if credit:
        headers["Link"] = f'<{credit["license_url"]}>; rel="license", <{credit["source_url"]}>; rel="describedby"'
    return Response(asset["content"], media_type="image/jpeg", headers=headers)


@router.get("/v1/listings/{listing_id}/photo-credits")
async def photo_credits(listing_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            """SELECT m.id,m.credit FROM catalog_media m JOIN catalog_listings l ON l.id=m.listing_id
            WHERE l.id=$1 AND l.status='published' AND NOT l.is_hidden AND m.id=ANY(l.photo_ids) AND m.kind='public_photo' """,
            listing_id,
        )
    return {
        "items": [
            {
                "asset_id": str(row["id"]),
                "credit": credit_projection(row["credit"]),
            }
            for row in rows
        ]
    }
