"""Bounded projection of current public facts; no release authority."""
import asyncio
import re
from datetime import datetime

PURCHASE_REFERENCE = re.compile(r"[a-zA-Z0-9-]{1,80}")

STATES = {"ready", "pending", "denied", "stale", "unavailable"}


def project(subject, operation, facts, page=1):
    identity = facts["identity"]
    state = identity.get("state", "unavailable")
    result = {
        "schema_version": "public-profile.v1", "operation_id": operation,
        "subject_id": subject, "revision": 0, "state": state if state in STATES else "unavailable",
        "identity": None, "sales": {"state": "unavailable", "released_count": None},
        "reviews": {"state": "unavailable", "distribution": None},
        "listings": {"state": "unavailable", "items": [], "total": None, "page": page, "page_size": 20},
    }
    if state != "ready":
        return result
    if identity["subject_id"] != subject or identity["active"] is not True or identity["public_permitted"] is not True:
        result["state"] = "denied"
        return result
    kind = identity["kind"]
    if kind not in {"private", "dealer"}:
        raise ValueError("Invalid seller type")
    if kind == "dealer" and identity["organization_active"] is not True:
        result["state"] = "denied"
        return result
    if not isinstance(identity["public_name"], str) or not 1 <= len(identity["public_name"]) <= 180:
        raise ValueError("Invalid public name")
    if identity.get("city_permitted") is True and identity.get("city") is not None and (not isinstance(identity["city"], str) or not 1 <= len(identity["city"]) <= 120):
        raise ValueError("Invalid public city")
    member = datetime.fromisoformat(identity["member_since"].replace("Z", "+00:00"))
    if member.tzinfo is None or member.utcoffset().total_seconds() != 0:
        raise ValueError("UTC membership required")
    verification = "private_seller_approved" if kind == "private" else "dealer_business_verified"
    if identity["verification"] != verification or type(identity["revision"]) is not int or identity["revision"] < 1:
        raise ValueError("Invalid verification")
    result["revision"] = identity["revision"]
    result["identity"] = {"name": identity["public_name"], "city": identity.get("city") if identity.get("city_permitted") is True else None,
        "kind": kind, "member_since": member.isoformat(), "verification": verification, "logo": None, "banner": None}
    for key in ("logo", "banner"):
        value = identity.get(key)
        if kind == "dealer" and identity.get(key + "_approved") is True and isinstance(value, str) and re.fullmatch(r"/media/[a-zA-Z0-9/_-]{1,180}\.(png|jpg|jpeg)", value):
            result["identity"][key] = value
    released = None
    for section in ("sales", "reviews", "listings"):
        try:
            source = facts.get(section, {"state": "unavailable"})
            status = source.get("state", "unavailable")
            if status == "ready" and (source.get("subject_id") != subject or source.get("identity_revision") != identity["revision"]):
                status = "stale"
            result[section]["state"] = status if status in STATES else "unavailable"
            if status != "ready":
                continue
            rows = source["items"]
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("Source budget exceeded")
            if section == "sales":
                purchases = {}
                for row in rows:
                    if row["seller_id"] != subject:
                        raise ValueError("Wrong seller")
                    if type(row["release_revision"]) is not int or row["release_revision"] < 1:
                        raise ValueError("Invalid release revision")
                    key, fact = row["purchase_id"], (row["state"], row["release_revision"])
                    if not isinstance(key, str) or not PURCHASE_REFERENCE.fullmatch(key):
                        raise ValueError("Invalid purchase reference")
                    if key in purchases and purchases[key] != fact:
                        raise ValueError("Conflicting release")
                    purchases[key] = fact
                released = {key for key, value in purchases.items() if value[0] == "released"}
                result[section]["released_count"] = len(released)
            elif section == "reviews":
                if released is None:
                    result[section]["state"] = "unavailable"
                    continue
                ratings = {}
                for row in rows:
                    key, rating = row["purchase_id"], row["rating"]
                    if not isinstance(key, str) or not PURCHASE_REFERENCE.fullmatch(key):
                        raise ValueError("Invalid purchase reference")
                    if key not in released or type(rating) is not int or not 1 <= rating <= 5 or key in ratings:
                        raise ValueError("Invalid released review")
                    ratings[key] = rating
                result[section]["distribution"] = [list(ratings.values()).count(star) for star in range(1, 6)]
            else:
                total = source["total"]
                if source["page"] != page or type(total) is not int or total < 0 or len(rows) != min(20, max(0, total - (page - 1) * 20)):
                    raise ValueError("Invalid listing page")
                if len({row["id"] for row in rows}) != len(rows) or any(row["seller_id"] != subject or row["state"] != "available_published" for row in rows):
                    raise ValueError("Listing unavailable")
                if any(not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", row["id"]) or not isinstance(row["title"], str) or not 1 <= len(row["title"]) <= 300 for row in rows):
                    raise ValueError("Invalid listing facts")
                result[section].update(items=[{"id": row["id"], "title": row["title"]} for row in rows], total=total)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            result[section]["state"] = "unavailable"
    return result


async def read_profile(provider, subject, operation, page=1):
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", subject) or not isinstance(operation, str) or not PURCHASE_REFERENCE.fullmatch(operation) or type(page) is not int or not 1 <= page <= 100000:
        raise ValueError("Invalid request")
    try:
        async with asyncio.timeout(2):
            return project(subject, operation, await provider(subject, page), page)
    except (TimeoutError, OSError, KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return project(subject, operation, {"identity": {"state": "unavailable"}}, page)
