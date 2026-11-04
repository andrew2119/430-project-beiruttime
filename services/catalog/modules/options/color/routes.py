"""CP B-08/B-09/B-18: guarded writes, stored first outcomes and atomic event intent."""

import hashlib
import json
import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
import asyncpg
from fastapi import APIRouter, Query, Request, Response
from bt_contracts.catalog.options import Kind, OptionWrite, SelectionWrite
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work as foundation_unit_of_work
from bt_runtime.principal import require_scope
from . import dependencies
from .images import safe_png

router = APIRouter(prefix="/v1/brand-options", tags=["brand-options-v1"])


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def error(code, message, status=409):
    return PublicError(code, message, status=status)


@asynccontextmanager
async def unit_of_work(pool, *, lock_key=None):
    try:
        async with foundation_unit_of_work(pool, lock_key=lock_key) as tx:
            yield tx
    except (
        TimeoutError,
        asyncpg.InterfaceError,
        asyncpg.PostgresConnectionError,
        asyncpg.QueryCanceledError,
        asyncpg.LockNotAvailableError,
        asyncpg.DeadlockDetectedError,
    ):
        # The foundation transaction exits/rolls back before retryable storage errors are exposed.
        raise error(
            "storage_unavailable", "Saved choices are temporarily unavailable. Retry the same operation.", 503
        ) from None


def operation_key(request):
    key = request.headers.get("idempotency-key", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        raise error("idempotency_required", "Supply an 8–100 character operation key.", 422)
    return key


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def replay(tx, owner, key, fingerprint):
    row = await tx.fetchrow(
        "SELECT digest,result FROM l10_operations WHERE owner_id=$1 AND operation_key=$2", owner, key
    )
    if row:
        if row["digest"] != fingerprint:
            raise error("idempotency_conflict", "This operation key belongs to a different request.")
        return decode(row["result"])
    return None


async def record(tx, request, owner, key, fingerprint, result, event_type, subject):
    await tx.execute(
        "INSERT INTO l10_operations(owner_id,operation_key,digest,result) VALUES($1,$2,$3,$4::jsonb)",
        owner,
        key,
        fingerprint,
        json.dumps(result),
    )
    await enqueue(
        tx,
        EventEnvelope(
            type=event_type,
            source="catalog",
            subject=str(subject),
            request_id=request.state.request_id,
            data={"resource_id": str(subject), "revision": result["revision"]},
        ),
        ["communications"],
    )
    return result


async def owned(tx, configuration_id, owner):
    row = await tx.fetchrow("SELECT * FROM l10_configurations WHERE id=$1 AND owner_id=$2", configuration_id, owner)
    if not row:
        raise error("not_found", "Configuration not found.", 404)
    return row


async def snapshot(tx, config):
    rows = await tx.fetch(
        """SELECT s.kind,s.component,s.option_id,s.option_revision,s.reference_ids,o.definition,
        (SELECT max(n.revision) FROM l10_options n WHERE n.brand_id=s.brand_id AND n.kind=s.kind AND n.option_id=s.option_id) AS latest_revision
        FROM l10_selections s JOIN l10_options o ON (o.brand_id,o.kind,o.option_id,o.revision)=
        (s.brand_id,s.kind,s.option_id,s.option_revision) WHERE s.configuration_id=$1 ORDER BY s.kind,s.component""",
        config["id"],
    )
    references = await tx.fetch(
        "SELECT id FROM l10_references WHERE configuration_id=$1 AND owner_id=$2 ORDER BY created_at,id",
        config["id"],
        config["owner_id"],
    )
    return {
        "id": str(config["id"]),
        "brand_id": str(config["brand_id"]),
        "base_model": config["base_model"],
        "caliber": config["caliber"],
        "revision": config["revision"],
        "state": "saved_not_submitted",
        "feasibility": "not_assessed",
        "reference_ids": [str(row["id"]) for row in references],
        "updated_at": config["updated_at"].isoformat(),
        "selections": [
            {
                "kind": r["kind"],
                "component": r["component"],
                "option_id": str(r["option_id"]),
                "option_revision": r["option_revision"],
                "reference_ids": [str(i) for i in r["reference_ids"]],
                "definition": decode(r["definition"]),
                "current": r["option_revision"] == r["latest_revision"] and decode(r["definition"])["available"],
            }
            for r in rows
        ],
    }


@router.get("/brands")
async def list_brands(request: Request, after: UUID | None = None):
    return await dependencies.brands(request, after)


@router.get("/brands/{brand_id}")
async def catalog(brand_id: UUID, request: Request):
    brand = await dependencies.brand(request, brand_id)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            """SELECT DISTINCT ON(kind,option_id) kind,option_id,revision,definition FROM l10_options
            WHERE brand_id=$1 ORDER BY kind,option_id,revision DESC LIMIT 201""",
            brand_id,
        )
    if len(rows) > 200:
        raise error("catalog_limit", "Narrow the brand catalog before continuing.", 503)
    return {
        "brand": brand.model_dump(mode="json"),
        "items": [
            {"kind": r["kind"], "id": str(r["option_id"]), "revision": r["revision"], **decode(r["definition"])}
            for r in rows
        ],
    }


@router.put("/brands/{brand_id}/{kind}/{option_id}")
async def publish(brand_id: UUID, kind: Kind, option_id: UUID, body: OptionWrite, request: Request):
    principal = await dependencies.principal(request, organization_id=brand_id)
    require_scope(principal, "business.jobs.write", brand_id)
    validator = request.app.state.hooks.get(f"catalog.options-{kind}.v1")
    if validator is None:
        raise error("option_kind_unavailable", "This option category is unavailable.", 503)
    try:
        details = validator(body.details, body.component)
    except ValueError:
        raise error("invalid_option", "Check the option definition and component.", 422) from None
    key, owner = operation_key(request), principal.actor.subject_id
    definition = {**body.model_dump(mode="json", exclude={"expected_revision"}), "details": details}
    fingerprint = digest({"publish": str(brand_id), "kind": kind, "id": str(option_id), **body.model_dump(mode="json")})
    async with unit_of_work(request.app.state.pool, lock_key=f"l10-op:{owner}:{key}") as tx:
        old = await replay(tx, owner, key, fingerprint)
        if old is not None:
            return old
        await dependencies.brand(request, brand_id)
        # Serialize the bounded catalog as well as each option's revision admission.
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-brand:{brand_id}")
        revision = (
            await tx.fetchval(
                "SELECT max(revision) FROM l10_options WHERE brand_id=$1 AND kind=$2 AND option_id=$3",
                brand_id,
                kind,
                option_id,
            )
            or 0
        )
        if revision != body.expected_revision:
            raise error("stale_option", "Reload the current option revision.")
        if revision == 0:
            count = await tx.fetchval("SELECT count(DISTINCT (kind,option_id)) FROM l10_options WHERE brand_id=$1", brand_id)
            if count >= 200:
                raise error("catalog_limit", "The brand catalog is full.")
        revision += 1
        await tx.execute(
            """INSERT INTO l10_options(brand_id,kind,option_id,revision,definition,created_by)
            VALUES($1,$2,$3,$4,$5::jsonb,$6)""",
            brand_id,
            kind,
            option_id,
            revision,
            json.dumps(definition),
            owner,
        )
        result = {"brand_id": str(brand_id), "kind": kind, "id": str(option_id), "revision": revision, **definition}
        return await record(
            tx, request, owner, key, fingerprint, result, "catalog.brand-option-published.v1", option_id
        )


@router.get("/configurations")
async def list_configurations(request: Request):
    principal = await dependencies.principal(request)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            "SELECT * FROM l10_configurations WHERE owner_id=$1 ORDER BY updated_at DESC,id LIMIT 50",
            principal.actor.subject_id,
        )
    return {
        "items": [
            {
                "id": str(r["id"]),
                "brand_id": str(r["brand_id"]),
                "base_model": r["base_model"],
                "caliber": r["caliber"],
                "revision": r["revision"],
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/configurations/{configuration_id}")
async def get_configuration(
    configuration_id: UUID, request: Request, expected_revision: int | None = Query(default=None, ge=1, le=2147483647)
):
    principal = await dependencies.principal(request)
    async with unit_of_work(request.app.state.pool, lock_key=f"l10-config:{configuration_id}") as tx:
        config = await owned(tx, configuration_id, principal.actor.subject_id)
        if expected_revision is not None and config["revision"] != expected_revision:
            raise error("stale_configuration", "Reload your saved choices before continuing.")
        return await snapshot(tx, config)


@router.put("/configurations/{configuration_id}/{kind}")
async def select(configuration_id: UUID, kind: Kind, body: SelectionWrite, request: Request):
    principal = await dependencies.principal(request)
    if "buyer" not in principal.roles:
        raise error("forbidden", "A buyer account is required.", 403)
    key, owner = operation_key(request), principal.actor.subject_id
    fingerprint = digest({"select": str(configuration_id), "kind": kind, **body.model_dump(mode="json")})
    async with unit_of_work(request.app.state.pool, lock_key=f"l10-op:{owner}:{key}") as tx:
        old = await replay(tx, owner, key, fingerprint)
        if old is not None:
            return old
        await dependencies.brand(request, body.brand_id)
        # Share catalog admission with publication: a revision cannot change between validation and commit.
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-brand:{body.brand_id}")
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-config:{configuration_id}")
        exists = await tx.fetchrow("SELECT * FROM l10_configurations WHERE id=$1", configuration_id)
        if exists and exists["owner_id"] != owner:
            raise error("not_found", "Configuration not found.", 404)
        if exists and (
            exists["brand_id"] != body.brand_id
            or exists["base_model"] != body.base_model
            or exists["caliber"] != body.caliber
        ):
            raise error(
                "configuration_binding", "Start a separate configuration for a different brand, base or caliber."
            )
        revision = exists["revision"] if exists else 0
        if revision != body.expected_revision:
            raise error("stale_configuration", "Reload your saved choices before saving again.")
        option = await tx.fetchrow(
            """SELECT revision,definition FROM l10_options WHERE brand_id=$1 AND kind=$2 AND option_id=$3
            ORDER BY revision DESC LIMIT 1""",
            body.brand_id,
            kind,
            body.option_id,
        )
        if not option or option["revision"] != body.option_revision:
            raise error("stale_option", "Choose a current, brand-supported option.")
        definition = decode(option["definition"])
        if (
            not definition["available"]
            or definition["component"] != body.component
            or body.base_model not in definition["base_models"]
            or body.caliber not in definition["calibers"]
        ):
            raise error("unsupported_option", "This option is unavailable for the selected component, base or caliber.")
        if body.reference_ids:
            if kind != "dial" or len(set(body.reference_ids)) != len(body.reference_ids):
                raise error("unsafe_reference", "References are only supported for a dial design.", 422)
            count = await tx.fetchval(
                "SELECT count(*) FROM l10_references WHERE id=ANY($1::uuid[]) AND configuration_id=$2 AND owner_id=$3",
                body.reference_ids,
                configuration_id,
                owner,
            )
            if count != len(body.reference_ids):
                raise error("unsafe_reference", "One or more references are not available to this configuration.", 422)
        if not exists:
            await tx.execute(
                "INSERT INTO l10_configurations(id,owner_id,brand_id,base_model,caliber) VALUES($1,$2,$3,$4,$5)",
                configuration_id,
                owner,
                body.brand_id,
                body.base_model,
                body.caliber,
            )
        await tx.execute(
            """INSERT INTO l10_selections(configuration_id,kind,component,brand_id,option_id,option_revision,reference_ids)
            VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(configuration_id,kind,component) DO UPDATE SET
            option_id=excluded.option_id,option_revision=excluded.option_revision,reference_ids=excluded.reference_ids""",
            configuration_id,
            kind,
            body.component,
            body.brand_id,
            body.option_id,
            body.option_revision,
            body.reference_ids,
        )
        config = await tx.fetchrow(
            "UPDATE l10_configurations SET revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
            configuration_id,
        )
        result = await snapshot(tx, config)
        return await record(
            tx, request, owner, key, fingerprint, result, "catalog.brand-selection-saved.v1", configuration_id
        )


@router.post("/configurations/{configuration_id}/references")
async def upload_reference(configuration_id: UUID, request: Request):
    principal = await dependencies.principal(request)
    if request.headers.get("content-type", "").split(";")[0] != "image/png":
        raise error("unsafe_reference", "Only PNG reference images are supported.", 422)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 1048576:
            raise error("reference_too_large", "The image must be under 1 MiB.", 413)
    image = safe_png(bytes(content))
    key, owner = operation_key(request), principal.actor.subject_id
    fingerprint = digest({"reference": str(configuration_id), "sha256": hashlib.sha256(image).hexdigest()})
    async with unit_of_work(request.app.state.pool, lock_key=f"l10-op:{owner}:{key}") as tx:
        old = await replay(tx, owner, key, fingerprint)
        if old is not None:
            return old
        await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-config:{configuration_id}")
        config = await owned(tx, configuration_id, owner)
        count = await tx.fetchval("SELECT count(*) FROM l10_references WHERE configuration_id=$1", configuration_id)
        if count >= 3:
            raise error("reference_limit", "A configuration supports at most three private reference images.")
        reference_id = uuid4()
        await tx.execute(
            "INSERT INTO l10_references(id,configuration_id,owner_id,content,sha256) VALUES($1,$2,$3,$4,$5)",
            reference_id,
            configuration_id,
            owner,
            image,
            hashlib.sha256(image).hexdigest(),
        )
        result = {
            "id": str(reference_id),
            "configuration_id": str(configuration_id),
            "revision": config["revision"],
            "media_type": "image/png",
        }
        # References stay private: no reference IDs or bytes enter events.
        return await record(
            tx, request, owner, key, fingerprint, result, "catalog.brand-reference-saved.v1", configuration_id
        )


@router.get("/configurations/{configuration_id}/references/{reference_id}")
async def read_reference(configuration_id: UUID, reference_id: UUID, request: Request):
    principal = await dependencies.principal(request)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow(
            "SELECT content FROM l10_references WHERE id=$1 AND configuration_id=$2 AND owner_id=$3",
            reference_id,
            configuration_id,
            principal.actor.subject_id,
        )
    if not row:
        raise error("not_found", "Reference not found.", 404)
    return Response(
        bytes(row["content"]),
        media_type="image/png",
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
