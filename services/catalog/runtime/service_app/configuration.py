"""Catalog-local configuration snapshot API. Borrow caller transaction, never commit."""

import hashlib
import json
from uuid import UUID
from bt_contracts_core.errors import PublicError

DIMENSIONS = ("color", "material", "dial", "sophistication", "movement")


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def fail(fields):
    raise PublicError(
        "configuration_incomplete", "Review the highlighted current selections.", status=422, details={"fields": fields}
    )


def classify(fields, rule_status=None):
    if any(code in ("other_brand", "unsupported_base", "unsupported_mounting") for code in fields.values()):
        return "incompatible"
    if "parts_unavailable" in fields.values():
        return "parts_unavailable"
    if fields:
        return "incompatible"
    return rule_status or "manual_assessment"


async def selections(tx, *, brand_id, base_model, caliber, chosen, mounting, reference_ids=()):
    """Validate exact all-five revisions. Same-service tables, no cross-domain SQL."""
    fields, saved = {}, {}
    if set(chosen) != set(DIMENSIONS):
        fail({dimension: "missing" for dimension in DIMENSIONS if dimension not in chosen})
    for kind in DIMENSIONS:
        selection = chosen[kind]
        option_id = UUID(str(selection["option_id"]))
        if kind == "movement":
            option = await tx.fetchrow("SELECT * FROM movement_options WHERE id=$1 FOR SHARE", option_id)
            if not option or option["brand_id"] != brand_id:
                fields[kind] = "other_brand"
                continue
            if option["revision"] != selection["option_revision"]:
                fields[kind] = "stale_option"
            if not option["active"]:
                fields[kind] = "parts_unavailable"
            if option["caliber"] != caliber:
                fields[kind] = "unsupported_base"
            if any(
                mounting.get(key) not in option[plural]
                for key, plural in (("case", "cases"), ("dial", "dials"), ("hands", "hands"))
            ) or not set(mounting.get("functions", [])).issubset(option["functions"]):
                fields[kind] = "unsupported_mounting"
            definition = {
                key: option[key]
                for key in (
                    "label_en",
                    "label_ar",
                    "caliber",
                    "cases",
                    "dials",
                    "hands",
                    "functions",
                    "quote_minor",
                    "currency",
                    "active",
                )
            }
            definition["indicative_only"] = True
        else:
            option = await tx.fetchrow(
                "SELECT * FROM l10_options WHERE brand_id=$1 AND kind=$2 AND option_id=$3 ORDER BY revision DESC LIMIT 1",
                brand_id,
                kind,
                option_id,
            )
            if not option:
                fields[kind] = "other_brand"
                continue
            if option["revision"] != selection["option_revision"]:
                fields[kind] = "stale_option"
            definition = decode(option["definition"])
            if base_model not in definition["base_models"] or caliber not in definition["calibers"]:
                fields[kind] = "unsupported_base"
            if not definition["available"]:
                fields[kind] = "parts_unavailable"
        saved[kind] = {"option_id": str(option_id), "option_revision": option["revision"], "definition": definition}
    if any(code == "stale_option" for code in fields.values()):
        fail(fields)
    snapshot = {
        "brand_id": str(brand_id),
        "base_model": base_model,
        "caliber": caliber,
        "selections": saved,
        "movement_mounting": mounting,
        "reference_ids": [str(i) for i in reference_ids],
    }
    rule = (
        await tx.fetchrow(
            """SELECT * FROM (SELECT DISTINCT ON(id) * FROM catalog_compatibility_rules
        WHERE brand_id=$1 ORDER BY id,revision DESC) r WHERE base_model=$2 AND caliber=$3
        AND option_ids @> $4::uuid[] AND option_ids <@ $4::uuid[] AND mounting=$5::jsonb AND option_revisions=$6::jsonb ORDER BY created_at DESC,id LIMIT 1""",
            brand_id,
            base_model,
            caliber,
            [UUID(entry["option_id"]) for entry in saved.values()],
            json.dumps(mounting),
            json.dumps({entry["option_id"]: entry["option_revision"] for entry in saved.values()}),
        )
        if len(saved) == 5
        else None
    )
    snapshot["compatibility_rule"] = (
        {"id": str(rule["id"]), "revision": rule["revision"], "reason": rule["reason"]} if rule else None
    )
    status = classify(fields, rule["status"] if rule else None)
    snapshot["compatibility_status"] = status
    return {
        "status": status,
        "fields": fields,
        "snapshot": snapshot,
        "digest": digest(snapshot),
        "physical_feasibility_pass": False,
        "price_acceptance": False,
    }


async def configuration(
    tx, owner_id, configuration_id, configuration_revision, movement_selection_id, movement_revision
):
    # Match existing mutation locks before reading all-five and preserve lock order.
    await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"movement-selection:{owner_id}")
    config = await tx.fetchrow(
        "SELECT * FROM l10_configurations WHERE id=$1 AND owner_id=$2", configuration_id, owner_id
    )
    if not config:
        raise PublicError("not_found", "Configuration not found.", status=404)
    await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-brand:{config['brand_id']}")
    await tx.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-config:{configuration_id}")
    config = await tx.fetchrow(
        "SELECT * FROM l10_configurations WHERE id=$1 AND owner_id=$2 FOR SHARE", configuration_id, owner_id
    )
    if config["revision"] != configuration_revision:
        fail({"configuration": "stale_revision"})
    rows = await tx.fetch(
        "SELECT kind,option_id,option_revision,reference_ids FROM l10_selections WHERE configuration_id=$1",
        configuration_id,
    )
    chosen = {}
    for row in rows:
        if row["kind"] in chosen:
            fail({row["kind"]: "ambiguous_components"})
        chosen[row["kind"]] = {"option_id": row["option_id"], "option_revision": row["option_revision"]}
    movement = await tx.fetchrow(
        "SELECT * FROM movement_selections WHERE id=$1 AND actor_id=$2 AND brand_id=$3",
        movement_selection_id,
        owner_id,
        config["brand_id"],
    )
    if not movement:
        fail({"movement": "missing"})
    if movement["revision"] != movement_revision:
        fail({"movement": "stale_revision"})
    chosen["movement"] = {"option_id": movement["option_id"], "option_revision": movement["option_revision"]}
    # Uploaded inventory is private until explicitly attached to a dial selection.
    attached = sorted({reference for row in rows if row["kind"] == "dial" for reference in row["reference_ids"]})
    references = await tx.fetch(
        "SELECT id FROM l10_references WHERE configuration_id=$1 AND owner_id=$2 AND id=ANY($3::uuid[]) ORDER BY id",
        configuration_id,
        owner_id,
        attached,
    )
    if len(attached) > 3 or len(references) != len(attached):
        fail({"dial": "unsafe_reference"})
    return await selections(
        tx,
        brand_id=config["brand_id"],
        base_model=config["base_model"],
        caliber=config["caliber"],
        chosen=chosen,
        mounting=decode(movement["configuration"]),
        reference_ids=[r["id"] for r in references],
    )
