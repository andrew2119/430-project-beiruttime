"""Bounded consumer of the released Service Directory V1 public projection."""

from uuid import UUID
from .dependencies import read

CAPABILITIES = {"maintenance", "cleaning", "polishing", "repair", "bracelet_fit", "customization"}


def business(value, purpose, expected_id=None):
    if not isinstance(value, dict):
        raise ValueError()
    identity = str(UUID(value["organization_id"]))
    if expected_id and identity != str(expected_id):
        raise ValueError()
    if type(value["revision"]) is not int or not 1 <= value["revision"] <= 2147483647:
        raise ValueError()
    if not isinstance(value["display_name"], str) or not 1 <= len(value["display_name"]) <= 160:
        raise ValueError()
    if type(value["sample"]) is not bool or value["kind"] not in ("brand", "dealer"):
        raise ValueError()
    capabilities = value["capabilities"]
    if not isinstance(capabilities, list) or not capabilities or len(capabilities) > 6:
        raise ValueError()
    if any(not isinstance(item, str) or item not in CAPABILITIES for item in capabilities):
        raise ValueError()
    if purpose == "customization" and (value["kind"] != "brand" or "customization" not in capabilities):
        raise ValueError()
    if purpose == "servicing" and not any(item != "customization" for item in capabilities):
        raise ValueError()
    # Contact/scope text is public but unnecessary here; never copy an arbitrary provider payload.
    return {
        "id": identity,
        "name": value["display_name"],
        "kind": value["kind"],
        "sample_content": value["sample"],
        "revision": value["revision"],
    }


async def catalogue(request, purpose, after=None):
    path = f"/v1/directory/businesses?purpose={purpose}&limit=20"
    if after:
        path += "&after=" + str(after)
    result = await read(request, "directory", path)
    if result["status"] != "available":
        return result
    try:
        value = result["data"]
        items = value["items"]
        cursor = value["next_after"]
        if not isinstance(items, list) or len(items) > 20:
            raise ValueError()
        rows = [business(item, purpose) for item in items]
        if len({item["id"] for item in rows}) != len(rows):
            raise ValueError()
        if cursor is not None:
            cursor = str(UUID(cursor))
            if after and UUID(cursor).int <= after.int:
                raise ValueError()
        return {"status": "available", "data": {"items": rows, "next_after": cursor}}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"status": "unavailable"}


async def current(request, organization_id, purpose):
    result = await read(request, "directory", f"/v1/directory/businesses/{organization_id}")
    if result["status"] != "available":
        return result
    try:
        return {"status": "available", "data": business(result["data"], purpose, organization_id)}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"status": "unavailable"}
