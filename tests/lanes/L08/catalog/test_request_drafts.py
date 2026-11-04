import asyncio
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.app import db


@pytest_asyncio.fixture
async def drafts(database_url):
    app = create_app(Settings(database_url=database_url, service_name="catalog"))
    app.state.pool = await db.create_pool(database_url)
    users = {}
    unavailable = set()
    configurations = {}
    app.state.proof_configurations = configurations
    app.state.proof_directory_requests = []

    def upstream(request):
        if request.url.host in unavailable:
            return httpx.Response(503)
        if request.url.host == "identity":
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if token not in users:
                return httpx.Response(401)
            return httpx.Response(200, json=users[token])
        if request.url.host == "options" and request.url.path.startswith("/v1/brand-options/configurations/"):
            key = request.url.path.rsplit("/", 1)[-1]
            entry = configurations.get(key)
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if not entry or entry[0] != token:
                return httpx.Response(404)
            if str(entry[1]["revision"]) != request.url.params.get("expected_revision"):
                return httpx.Response(409)
            return httpx.Response(200, json=entry[1])
        if request.url.host == "directory":
            app.state.proof_directory_requests.append(str(request.url))
            if hasattr(app.state, "proof_directory_payload"):
                return httpx.Response(200, json=app.state.proof_directory_payload)
            profile = {
                "organization_id": str(uuid4()),
                "revision": 1,
                "display_name": "Labeled sample brand",
                "kind": "brand",
                "sample": True,
                "capabilities": ["customization", "repair"],
                "contact": "Sample public contact",
                "visit_en": "Sample",
                "visit_ar": "مثال",
                "scope_en": "Sample",
                "scope_ar": "مثال",
            }
            if request.url.path == "/v1/directory/businesses":
                return httpx.Response(200, json={"items": [profile], "next_after": None})
            if request.url.path.startswith("/v1/directory/businesses/"):
                return httpx.Response(200, json={**profile, "organization_id": request.url.path.rsplit("/", 1)[-1]})
            return httpx.Response(404)
        return httpx.Response(
            200, json={"items": [{"id": "sample-color", "label": "Sample color", "dimension": "color"}]}
        )

    app.state.draft_clients = {
        name: DependencyClient(name, "http://" + name, transport=httpx.MockTransport(upstream))
        for name in ("identity", "directory", "options", "communications")
    }
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://catalog")

    def user(roles=None):
        identity = str(uuid4())
        users[identity] = {"actor": {"subject_id": identity, "session_id": "test"}, "roles": roles or ["buyer"]}
        return {"Authorization": "Bearer " + identity}

    yield app, client, user, unavailable
    await client.aclose()
    for dependency in app.state.draft_clients.values():
        await dependency.aclose()
    await app.state.pool.close()


def body(**changes):
    return {
        "brand_id": str(uuid4()),
        "kind": "customization",
        "watch_context": "owned_watch",
        "watch_reference": "Sample owner watch",
        "scope_intent": "Assess strap options",
        "notes": "Private neutral note",
        "options": {"color": "sample-color"},
        **changes,
    }


@pytest.mark.asyncio
async def test_private_durable_draft_retry_stale_and_cross_account(drafts):
    app, c, user, unavailable = drafts
    owner = user()
    other = user()
    value = body()
    headers = {**owner, "Idempotency-Key": "create-draft"}
    responses = await asyncio.gather(
        c.post("/v1/request-drafts", json=value, headers=headers),
        c.post("/v1/request-drafts", json=value, headers=headers),
    )
    assert responses[0].json() == responses[1].json()
    current = responses[0].json()["draft"]
    id = current["id"]
    assert current["status"] == "draft" and current["approved"] is False and current["payment_authority"] is False
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_request_drafts") == 1
    assert (await c.get("/v1/request-drafts/" + id, headers=owner)).json() == current
    assert (await c.get("/v1/request-drafts/" + id, headers=other)).status_code == 404
    assert (await c.get("/v1/request-drafts", headers=other)).json()["items"] == []
    changes = {**value, "expected_revision": 1, "notes": "Updated private note"}
    path = "/v1/request-drafts/" + id
    updated = await c.patch(path, json=changes, headers={**owner, "Idempotency-Key": "update"})
    assert updated.json()["draft"]["revision"] == 2
    assert (await c.patch(path, json=changes, headers={**owner, "Idempotency-Key": "update"})).json() == updated.json()
    assert (await c.patch(path, json=changes, headers={**owner, "Idempotency-Key": "stale"})).status_code == 409
    assert (
        await c.patch(path, json={**changes, "expected_revision": 2}, headers={**other, "Idempotency-Key": "other"})
    ).status_code == 404
    assert (await c.post("/v1/request-drafts", json=body(notes="Different"), headers=headers)).status_code == 409
    # Recreate runtime and pool to prove acknowledged content survives process restart.
    second = create_app(app.state.settings)
    second.state.pool = await db.create_pool(app.state.settings.database_url)
    second.state.draft_clients = app.state.draft_clients
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url="http://catalog") as restored:
            persisted = (await restored.get(path, headers=owner)).json()
            assert persisted["notes"] == "Updated private note" and persisted["revision"] == 2
    finally:
        await second.state.pool.close()
    events = await app.state.pool.fetch("SELECT envelope FROM outbox")
    assert events and all(
        "Private neutral note" not in row["envelope"] and "Updated private note" not in row["envelope"]
        for row in events
    )


@pytest.mark.asyncio
async def test_real_reads_degrade_without_authorizing_future_actions(drafts):
    app, c, user, unavailable = drafts
    owner = user()
    current = (await c.post("/v1/request-drafts", json=body(), headers={**owner, "Idempotency-Key": "create"})).json()[
        "draft"
    ]
    path = "/v1/request-drafts/" + current["id"]
    state = (await c.get(path + "/readiness", headers=owner)).json()
    assert state["brand"]["status"] == "available" and state["options"]["status"] == "available"
    assert state["intake"]["status"] == "unavailable"
    assert all("/v1/directory/businesses" in path for path in app.state.proof_directory_requests)
    assert all(section["status"] == "unavailable" for section in state["sections"].values())
    for action in ("submit", "approve", "pay", "start", "complete", "collect"):
        response = await c.post(path + "/actions/" + action, headers=owner)
        assert response.status_code == 409 and response.json()["error"]["code"] == "capability_unreleased"
    unavailable.update(["directory", "options"])
    state = (await c.get(path + "/readiness", headers=owner)).json()
    assert state["brand"]["status"] == state["options"]["status"] == state["intake"]["status"] == "unavailable"
    assert (await c.get(path, headers=owner)).status_code == 200
    assert (
        await c.post("/v1/request-drafts", json=body(brand_id=None), headers={**owner, "Idempotency-Key": "neutral"})
    ).status_code == 200
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_request_drafts") == 2


@pytest.mark.asyncio
async def test_permission_validation_and_identity_unavailable(drafts):
    app, c, user, unavailable = drafts
    owner = user()
    operator = user(["operator"])
    assert (
        await c.post("/v1/request-drafts", json=body(), headers={**operator, "Idempotency-Key": "forbidden"})
    ).status_code == 403
    assert (
        await c.post("/v1/request-drafts", json=body(notes="x" * 4001), headers={**owner, "Idempotency-Key": "long"})
    ).status_code == 422
    assert (
        await c.post(
            "/v1/request-drafts",
            json=body(options={"arbitrary": "unsupported"}),
            headers={**owner, "Idempotency-Key": "invalid"},
        )
    ).status_code == 422
    assert (
        await c.post(
            "/v1/request-drafts", json={**body(), "approved": True}, headers={**owner, "Idempotency-Key": "fake"}
        )
    ).status_code == 422
    unavailable.add("identity")
    assert (
        await c.post("/v1/request-drafts", json=body(), headers={**owner, "Idempotency-Key": "unavailable"})
    ).status_code == 503
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_request_drafts") == 0


@pytest.mark.asyncio
async def test_concurrent_draft_edits_compare_revision_under_one_lock(drafts):
    app, c, user, unavailable = drafts
    owner = user()
    value = body(brand_id=None)
    current = (await c.post("/v1/request-drafts", json=value, headers={**owner, "Idempotency-Key": "create"})).json()[
        "draft"
    ]
    path = "/v1/request-drafts/" + current["id"]
    replies = await asyncio.gather(
        *(
            c.patch(
                path, json={**value, "expected_revision": 1, "notes": note}, headers={**owner, "Idempotency-Key": key}
            )
            for key, note in [("edit-one", "First edit"), ("edit-two", "Second edit")]
        )
    )
    assert sorted(response.status_code for response in replies) == [200, 409]
    latest = (await c.get(path, headers=owner)).json()
    assert latest["revision"] == 2 and latest["notes"] in ("First edit", "Second edit")
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_draft_audit") == 2
    assert await app.state.pool.fetchval("SELECT count(*) FROM l08_draft_operations") == 2


@pytest.mark.asyncio
async def test_bound_source_configuration_preserves_revisions_without_inventory_previews(drafts):
    import json

    app, c, user, unavailable = drafts
    owner = user()
    other = user()
    configuration_id = str(uuid4())
    brand_id = str(uuid4())
    attached = str(uuid4())
    unattached = str(uuid4())
    color, dial = str(uuid4()), str(uuid4())

    def definition(component):
        return {
            "component": component,
            "label": {"en": "Sample option", "ar": "خيار تجريبي"},
            "base_models": ["sample-base"],
            "calibers": ["sample-caliber"],
            "available": True,
            "details": {},
        }

    source = {
        "id": configuration_id,
        "brand_id": brand_id,
        "base_model": "sample-base",
        "caliber": "sample-caliber",
        "revision": 1,
        "state": "saved_not_submitted",
        "feasibility": "not_assessed",
        "reference_ids": [attached, unattached],
        "selections": [
            {
                "kind": "color",
                "component": "case",
                "option_id": color,
                "option_revision": 3,
                "reference_ids": [],
                "definition": definition("case"),
                "current": True,
            },
            {
                "kind": "dial",
                "component": "dial",
                "option_id": dial,
                "option_revision": 2,
                "reference_ids": [attached],
                "definition": definition("dial"),
                "current": False,
            },
        ],
    }
    app.state.proof_configurations[configuration_id] = (owner["Authorization"].removeprefix("Bearer "), source)
    value = body(brand_id=None, options={}, configuration_id=configuration_id, configuration_revision=1)
    response = await c.post("/v1/request-drafts", json=value, headers={**owner, "Idempotency-Key": "bind-source"})
    assert response.status_code == 200, response.text
    current = response.json()["draft"]
    draft_id = current["id"]
    assert current["brand_id"] == brand_id and current["options"] == {"color": color, "dial": dial}
    assert current["configuration_revision"] == 1 and current["approved"] is False
    assert "configuration_snapshot" not in current and attached not in response.text and unattached not in response.text
    content = json.loads(await app.state.pool.fetchval("SELECT content FROM l08_request_drafts"))
    assert content["configuration_snapshot"]["selections"][0]["option_revision"] == 3
    assert content["configuration_snapshot"]["selections"][1]["reference_ids"] == [attached]
    assert unattached not in json.dumps(content)
    projection = await c.get(
        "/v1/request-draft-configurations/" + configuration_id, params={"revision": 1}, headers=owner
    )
    assert projection.json()["selection_summary"][1]["current"] is False
    assert attached not in projection.text and unattached not in projection.text
    assert (
        await c.get("/v1/request-draft-configurations/" + configuration_id, params={"revision": 1}, headers=other)
    ).status_code == 409
    assert (
        await c.post("/v1/request-drafts", json=value, headers={**other, "Idempotency-Key": "foreign"})
    ).status_code == 409
    assert (
        await c.post(
            "/v1/request-drafts",
            json={**value, "brand_id": str(uuid4())},
            headers={**owner, "Idempotency-Key": "wrong-brand"},
        )
    ).status_code == 409
    assert (
        await c.post(
            "/v1/request-drafts",
            json={**value, "configuration_revision": None},
            headers={**owner, "Idempotency-Key": "unpaired"},
        )
    ).status_code == 422
    source["revision"] = 2
    replay = await c.post("/v1/request-drafts", json=value, headers={**owner, "Idempotency-Key": "bind-source"})
    assert replay.json() == response.json()
    stale = await c.patch(
        "/v1/request-drafts/" + draft_id,
        json={**value, "expected_revision": 1},
        headers={**owner, "Idempotency-Key": "stale-source"},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_configuration"
    assert (await c.get("/v1/request-drafts/" + draft_id, headers=owner)).json()["revision"] == 1
    readiness = (await c.get("/v1/request-drafts/" + draft_id + "/readiness", headers=owner)).json()
    assert readiness["configuration"] == {"status": "unavailable", "code": "stale_configuration"}
