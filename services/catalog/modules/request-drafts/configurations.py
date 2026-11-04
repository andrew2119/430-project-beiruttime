"""Consume released L10 configuration revisions, never reinterpret intent as approval."""

from copy import deepcopy
from uuid import UUID
from fastapi import HTTPException
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import PublicError
from .dependencies import clients

KINDS = {"color", "material", "dial", "sophistication"}
COMPONENTS = {"case", "bezel", "dial", "hands", "markers", "strap", "bracelet", "package"}


async def snapshot(request, configuration_id, revision):
    response = await clients(request.app)["options"].request(
        "GET",
        f"/v1/brand-options/configurations/{configuration_id}?expected_revision={revision}",
        headers={"Authorization": request.headers["Authorization"], "X-Request-ID": request.state.request_id},
    )
    if isinstance(response, Unavailable):
        raise PublicError(
            "configuration_unavailable", "The owned source configuration cannot be confirmed.", status=503
        )
    if response.status_code == 401:
        raise HTTPException(401)
    if response.status_code == 409:
        raise PublicError(
            "stale_configuration", "The source configuration changed. Reopen it before binding.", status=409
        )
    if response.status_code in (400, 403, 404, 410, 422):
        raise PublicError("configuration_unavailable", "A current owned configuration is required.", status=409)
    try:
        value = response.json()
        if response.status_code != 200 or not isinstance(value, dict):
            raise ValueError()
        if (
            UUID(value["id"]) != UUID(str(configuration_id))
            or type(value["revision"]) is not int
            or value["revision"] != revision
        ):
            raise ValueError()
        brand = str(UUID(value["brand_id"]))
        if value["state"] != "saved_not_submitted" or value["feasibility"] != "not_assessed":
            raise ValueError()
        if any(
            not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= 80 for key in ("base_model", "caliber")
        ):
            raise ValueError()
        selections = value["selections"]
        if not isinstance(selections, list) or not 1 <= len(selections) <= 5:
            raise ValueError()
        saved = []
        seen = set()
        for selection in selections:
            kind = selection["kind"]
            component = selection["component"]
            if kind not in KINDS or kind in seen or component not in COMPONENTS:
                raise ValueError()
            seen.add(kind)
            option_id = str(UUID(selection["option_id"]))
            version = selection["option_revision"]
            if type(version) is not int or not 1 <= version <= 2147483647 or type(selection["current"]) is not bool:
                raise ValueError()
            references = selection.get("reference_ids", [])
            if not isinstance(references, list) or len(references) > 3 or (references and kind != "dial"):
                raise ValueError()
            references = [str(UUID(reference)) for reference in references]
            definition = selection["definition"]
            if not isinstance(definition, dict) or set(definition) != {
                "component",
                "label",
                "base_models",
                "calibers",
                "available",
                "details",
            }:
                raise ValueError()
            if definition["component"] != component or type(definition["available"]) is not bool:
                raise ValueError()
            if value["base_model"] not in definition["base_models"] or value["caliber"] not in definition["calibers"]:
                raise ValueError()
            saved.append(
                {
                    "kind": kind,
                    "component": component,
                    "option_id": option_id,
                    "option_revision": version,
                    "reference_ids": references,
                    "definition": deepcopy(definition),
                    "current": selection["current"],
                }
            )
        # Deliberately omit top-level reference_ids: uploaded inventory is not attached evidence.
        return {
            "id": str(configuration_id),
            "brand_id": brand,
            "revision": revision,
            "base_model": value["base_model"],
            "caliber": value["caliber"],
            "state": "saved_not_submitted",
            "feasibility": "not_assessed",
            "selections": saved,
        }
    except (ValueError, KeyError, TypeError):
        raise PublicError(
            "configuration_unavailable", "The source configuration cannot be confirmed.", status=503
        ) from None


def safe_intent(value):
    return {
        "configuration_id": value["id"],
        "configuration_revision": value["revision"],
        "brand_id": value["brand_id"],
        "base_model": value["base_model"],
        "caliber": value["caliber"],
        "options": {entry["kind"]: entry["option_id"] for entry in value["selections"]},
        "selection_summary": [
            {key: entry[key] for key in ("kind", "component", "option_id", "option_revision", "current")}
            for entry in value["selections"]
        ],
    }


async def bind(request, content):
    if not content.get("configuration_id"):
        return content
    value = await snapshot(request, content["configuration_id"], content["configuration_revision"])
    if content.get("brand_id") not in (None, value["brand_id"]):
        raise PublicError("configuration_binding", "The source configuration belongs to a different brand.", status=409)
    for selection in value["selections"]:
        if content["options"].get(selection["kind"]) not in (None, "", selection["option_id"]):
            raise PublicError(
                "configuration_binding", "Change the source selection explicitly before saving.", status=409
            )
        content["options"][selection["kind"]] = selection["option_id"]
    content["brand_id"] = value["brand_id"]
    content["configuration_snapshot"] = value
    return content
