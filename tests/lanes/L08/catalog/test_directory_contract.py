from uuid import uuid4
import pytest
from test_request_drafts import drafts as draft_fixture

# Register the existing local fixture without creating a second database harness.
drafts = draft_fixture


def profile(**changes):
    return {
        "organization_id": str(uuid4()),
        "revision": 1,
        "display_name": "Sample official brand",
        "kind": "brand",
        "sample": True,
        "capabilities": ["customization", "repair"],
        **changes,
    }


@pytest.mark.asyncio
async def test_released_directory_purpose_cursor_and_minimal_projection(drafts):
    app, c, user, _ = drafts
    owner = user()
    cursor = str(uuid4())
    brand = profile()
    app.state.proof_directory_payload = {"items": [brand], "next_after": cursor}
    response = await c.get("/v1/request-draft-catalogue", headers=owner)
    assert response.json() == {
        "status": "available",
        "data": {
            "items": [
                {
                    "id": brand["organization_id"],
                    "revision": 1,
                    "name": brand["display_name"],
                    "kind": "brand",
                    "sample_content": True,
                }
            ],
            "next_after": cursor,
        },
    }
    assert (
        app.state.proof_directory_requests[-1]
        == "http://directory/v1/directory/businesses?purpose=customization&limit=20"
    )
    # Fresh eligibility can filter a complete scan page: do not erase its continuation cursor.
    app.state.proof_directory_payload = {"items": [], "next_after": "ffffffff-ffff-4fff-8fff-ffffffffffff"}
    page = (
        await c.get("/v1/request-draft-catalogue", params={"purpose": "servicing", "after": cursor}, headers=owner)
    ).json()
    assert page["status"] == "available" and page["data"]["items"] == [] and page["data"]["next_after"]
    assert app.state.proof_directory_requests[-1].endswith("purpose=servicing&limit=20&after=" + cursor)
    app.state.proof_directory_payload = {"items": [], "next_after": cursor}
    assert (await c.get("/v1/request-draft-catalogue", params={"after": cursor}, headers=owner)).json() == {
        "status": "unavailable"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"items": [], "next_after": "not-a-cursor"},
        {"items": [profile(kind="dealer")], "next_after": None},
        {"items": [profile(revision=True)], "next_after": None},
        {"items": [profile(sample="true")], "next_after": None},
        {"items": [profile(capabilities=["repair"])], "next_after": None},
        {"items": [profile(display_name="")], "next_after": None},
    ],
)
async def test_malformed_or_ineligible_directory_is_never_available(drafts, payload):
    app, c, user, _ = drafts
    app.state.proof_directory_payload = payload
    assert (await c.get("/v1/request-draft-catalogue", headers=user())).json() == {"status": "unavailable"}


@pytest.mark.asyncio
async def test_servicing_draft_uses_capability_filtered_profile_without_options_or_private_intake(drafts):
    app, c, user, _ = drafts
    owner = user()
    brand = profile(kind="dealer", capabilities=["repair"])
    app.state.proof_directory_payload = brand
    response = await c.post(
        "/v1/request-drafts",
        headers={**owner, "Idempotency-Key": "service-draft"},
        json={
            "brand_id": brand["organization_id"],
            "kind": "service",
            "watch_context": "owned_watch",
            "watch_reference": "Sample",
            "scope_intent": "Assessment only",
            "notes": "",
            "options": {},
        },
    )
    draft = response.json()["draft"]
    readiness = (await c.get("/v1/request-drafts/" + draft["id"] + "/readiness", headers=owner)).json()
    assert readiness["brand"]["status"] == "available"
    assert readiness["options"] == {"status": "not_applicable"} and readiness["intake"] == {"status": "unavailable"}
    assert len(app.state.proof_directory_requests) == 1
    app.state.proof_directory_payload = profile()
    assert (await c.get("/v1/request-drafts/" + draft["id"] + "/readiness", headers=owner)).json()["brand"] == {
        "status": "unavailable"
    }
