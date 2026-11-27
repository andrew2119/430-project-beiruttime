import json
from uuid import UUID
from fastapi import APIRouter, Request
from bt_contracts.catalog.configuration.v1 import Validate, Rule
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from service_app.catalog_dependencies import principal
from service_app.configuration import configuration, decode
from service_app.customization import active_brand

router = APIRouter()


@router.post("/v1/configurations/{configuration_id}/validate")
@router.post("/v2/configurations/{configuration_id}/validate")
async def validate(configuration_id: UUID, body: Validate, request: Request):
    person = await principal(request)
    if "buyer" not in person.roles or person.actor.organization_id:
        raise AccessDenied("Personal buyer scope required")
    async with request.app.state.pool.acquire() as tx:
        brand_id = await tx.fetchval(
            "SELECT brand_id FROM l10_configurations WHERE id=$1 AND owner_id=$2",
            configuration_id,
            person.actor.subject_id,
        )
    if brand_id is None:
        raise PublicError("not_found", "Configuration not found.", status=404)
    await active_brand(request, brand_id)
    async with unit_of_work(
        request.app.state.pool, lock_key=f"l15-validation:{configuration_id}"
    ) as tx:
        return await configuration(
            tx, person.actor.subject_id, configuration_id, **body.model_dump()
        )


@router.get("/v1/brands/{brand_id}/compatibility")
@router.get("/v2/brands/{brand_id}/compatibility")
async def rules(brand_id: UUID, request: Request):
    await active_brand(request, brand_id)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch(
            "SELECT DISTINCT ON(id) id,revision,base_model,caliber,mounting,option_revisions,option_ids,status,reason FROM catalog_compatibility_rules WHERE brand_id=$1 ORDER BY id,revision DESC LIMIT 200",
            brand_id,
        )
    return {
        "items": [
            {
                **dict(row),
                "mounting": decode(row["mounting"]),
                "option_revisions": decode(row["option_revisions"]),
            }
            for row in rows
        ]
    }


@router.put("/v1/brands/{brand_id}/compatibility/{rule_id}")
@router.put("/v2/brands/{brand_id}/compatibility/{rule_id}")
async def publish(brand_id: UUID, rule_id: UUID, body: Rule, request: Request):
    person = await principal(request)
    require_scope(person, "business.jobs.write", brand_id)
    await active_brand(request, brand_id)
    if (
        len(set(body.option_ids)) != 5
        or set(body.option_ids) != set(body.option_revisions)
        or any(revision < 1 for revision in body.option_revisions.values())
    ):
        raise PublicError(
            "invalid_rule", "Choose five distinct brand options.", status=422
        )
    async with unit_of_work(
        request.app.state.pool, lock_key=f"l10-brand:{brand_id}"
    ) as tx:
        old = await tx.fetchrow(
            "SELECT * FROM catalog_compatibility_rules WHERE id=$1 ORDER BY revision DESC LIMIT 1",
            rule_id,
        )
        if old and old["brand_id"] != brand_id:
            raise AccessDenied("Rule belongs to another brand")
        accepted = await tx.fetchrow(
            'SELECT * FROM catalog_compatibility_rules WHERE id=$1 AND revision=$2',
            rule_id, body.expected_revision + 1)
        if (accepted and accepted['actor_id'] == person.actor.subject_id
                and accepted['brand_id'] == brand_id
                and accepted['base_model'] == body.base_model and accepted['caliber'] == body.caliber
                and set(accepted['option_ids']) == set(body.option_ids)
                and decode(accepted['option_revisions']) == {str(key):value for key,value in body.option_revisions.items()}
                and decode(accepted['mounting']) == body.mounting.model_dump(mode='json')
                and accepted['status'] == body.status and accepted['reason'] == body.reason):
            # Recover the exact immutable PUT acknowledgement even after a later
            # rule/option revision; never create another version/event on replay.
            return {key:accepted[key] for key in ('id','revision','status')}
        if (old["revision"] if old else 0) != body.expected_revision:
            raise PublicError("stale_revision", "Reload the current rule.", status=409)
        count = await tx.fetchval(
            "SELECT count(DISTINCT id) FROM catalog_compatibility_rules WHERE brand_id=$1",
            brand_id,
        )
        if old is None and count >= 200:
            raise PublicError(
                "rule_limit", "The brand rule catalogue is full.", status=409
            )
        options = await tx.fetch(
            "SELECT DISTINCT ON(kind,option_id) kind,option_id,revision,definition FROM l10_options WHERE brand_id=$1 AND option_id=ANY($2::uuid[]) ORDER BY kind,option_id,revision DESC",
            brand_id,
            body.option_ids,
        )
        movement = await tx.fetchrow(
            "SELECT * FROM movement_options WHERE brand_id=$1 AND id=ANY($2::uuid[]) FOR SHARE",
            brand_id,
            body.option_ids,
        )
        if (
            len(options) != 4
            or {row["kind"] for row in options}
            != {"color", "material", "dial", "sophistication"}
            or movement is None
            or movement["caliber"] != body.caliber
        ):
            raise PublicError(
                "invalid_rule",
                "All five options must belong to this brand and caliber.",
                status=422,
            )
        if any(
            body.base_model not in decode(row["definition"])["base_models"]
            or body.caliber not in decode(row["definition"])["calibers"]
            for row in options
        ):
            raise PublicError(
                "invalid_rule",
                "The rule cannot combine another base or caliber.",
                status=422,
            )
        if any(
            getattr(body.mounting, key) not in movement[plural]
            for key, plural in (
                ("case", "cases"),
                ("dial", "dials"),
                ("hands", "hands"),
            )
        ) or not set(body.mounting.functions).issubset(movement["functions"]):
            raise PublicError(
                "invalid_rule",
                "The rule mounting is not supported by this movement.",
                status=422,
            )
        versions = {str(option["option_id"]): option["revision"] for option in options}
        versions[str(movement["id"])] = movement["revision"]
        if versions != {
            str(option): revision for option, revision in body.option_revisions.items()
        }:
            raise PublicError(
                "stale_option",
                "Review all five current option revisions before publishing a rule.",
                status=409,
            )
        row = await tx.fetchrow(
            "INSERT INTO catalog_compatibility_rules(id,brand_id,revision,base_model,caliber,option_ids,status,reason,actor_id,mounting,option_revisions) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb) RETURNING id,revision,status",
            rule_id,
            brand_id,
            body.expected_revision + 1,
            body.base_model,
            body.caliber,
            body.option_ids,
            body.status,
            body.reason,
            person.actor.subject_id,
            body.mounting.model_dump_json(),
            json.dumps(versions),
        )
        await enqueue(
            tx,
            EventEnvelope(
                type="catalog.compatibility.published.v1",
                source="catalog",
                subject=str(rule_id),
                request_id=request.state.request_id,
                data={
                    "brand_id": str(brand_id),
                    "rule_id": str(rule_id),
                    "revision": row["revision"],
                },
            ),
            ["service-operations-brand-assessment"],
        )
    return dict(row)
