import asyncio
import copy
import json
import struct
import zlib
from pathlib import Path
from uuid import UUID, uuid4
import httpx
import pytest
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.app.db import migrate

BRAND = UUID("20000000-0000-4000-8000-000000000001")
OTHER_BRAND = UUID("20000000-0000-4000-8000-000000000002")
BUYER = UUID("30000000-0000-4000-8000-000000000001")
OTHER_BUYER = UUID("30000000-0000-4000-8000-000000000002")
STAFF = UUID("40000000-0000-4000-8000-000000000001")
ROOT = "/v1/brand-options"
MODULES = Path("/app/modules")


def headers(token="buyer", key=None):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key or uuid4().hex}


def business(**overrides):
    return {'id': str(BRAND), 'public_name': 'Sample Atelier', 'kind': 'brand',
            'capabilities': ['customization'], 'state': 'active', 'revision': 1, 'sample': True,
            'platform_onboarded': True, 'authenticated_business': True,
            'independent_watch_authentication_required': False, **overrides}


def identity(request):
    assert request.method == "GET"
    if request.url.path == '/v1/businesses':
        return httpx.Response(200, json={'items': [business()]})
    assert request.url.path == "/internal/v1/principal"
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    if token == "offline":
        raise httpx.ConnectError("fixture outage")
    if token not in {"buyer", "other-buyer", "brand", "wrong-org", "no-grant", "stock-only"}:
        return httpx.Response(401)
    staff = token in {"brand", "wrong-org", "no-grant", "stock-only"}
    org = OTHER_BRAND if token == "wrong-org" else BRAND
    selected = request.url.params.get("organization_id")
    if selected and (not staff or selected != str(org)):
        return httpx.Response(403)
    return httpx.Response(
        200,
        json={
            "actor": {
                "subject_id": str(STAFF if staff else OTHER_BUYER if token == "other-buyer" else BUYER),
                "session_id": "sample-test-session",
                "organization_id": selected if staff else None,
            },
            "roles": ["brand"] if staff else ["buyer"],
            "permissions": [],
            "organizations": [str(org)] if staff else [],
            "organization_grants": [
                {
                    "organization_id": str(BRAND),
                    "roles": ["brand"],
                    "permissions": []
                    if token == "no-grant"
                    else ["business.stock.write"]
                    if token == "stock-only"
                    else ["business.jobs.write"],
                }
            ]
            if staff
            else [],
        },
    )


def directory(request):
    assert request.method == "GET" and request.url.path == "/v1/directory"
    assert dict(request.url.params) == {"kind": "brand", "offering": "customization"}
    return httpx.Response(
        200,
        json={
            "items": [
                {
                    "organization_id": str(BRAND),
                    "name": {"en": "Sample Atelier", "ar": "المشغل النموذجي"},
                    "kind": "brand",
                    "status": "onboarded",
                    "offerings": ["customization"],
                    "sample": True,
                },
                {
                    "organization_id": str(OTHER_BRAND),
                    "name": {"en": "Not onboarded", "ar": "غير معتمدة"},
                    "kind": "brand",
                    "status": "pending",
                    "offerings": ["customization"],
                    "sample": True,
                },
            ]
        },
    )


@pytest_asyncio.fixture
async def env(database_access):
    await migrate(database_access.owner_url, MODULES)
    app = create_app(Settings(service_name="catalog", database_url=database_access.runtime_url, modules_path=MODULES))
    async with app.router.lifespan_context(app):
        # Transport-only fixtures retain real orchestration, authorization, SQL and event writes.
        real = next(m for m in app.state.modules if m.id == "L10.options-color").load("dependencies.py:clients")(app)
        await real["identity"].aclose()
        await real["directory"].aclose()
        real["identity"] = DependencyClient(
            "identity", "http://identity", transport=httpx.MockTransport(identity), concurrency=2
        )
        real["directory"] = DependencyClient(
            "directory", "http://directory", transport=httpx.MockTransport(directory), concurrency=2
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://catalog") as client:
            yield app, client, database_access


def samples():
    from importlib.resources import files

    return json.loads(files("bt_contracts.catalog.options").joinpath("fixtures/options.v1.json").read_text())["options"]


async def publish(client, entry, *, brand=BRAND, token="brand", key=None):
    return await client.put(
        f"{ROOT}/brands/{brand}/{entry['kind']}/{entry['id']}", headers=headers(token, key), json=entry["definition"]
    )


async def populate(client):
    for entry in samples():
        response = await publish(client, entry)
        assert response.status_code == 200, response.text


def selection(entry, revision=0, **overrides):
    return {
        "brand_id": str(BRAND),
        "base_model": "atelier-38",
        "caliber": "manual-01",
        "component": entry["definition"]["component"],
        "option_id": entry["id"],
        "option_revision": 1,
        "expected_revision": revision,
        "reference_ids": [],
        **overrides,
    }


async def save(client, entry, config, revision=0, token="buyer", key=None, **overrides):
    return await client.put(
        f"{ROOT}/configurations/{config}/{entry['kind']}",
        headers=headers(token, key),
        json=selection(entry, revision, **overrides),
    )


@pytest.mark.asyncio
async def test_all_stories_saved_exactly_and_reloaded_after_restart(env):
    app, client, access = env
    await populate(client)
    config = uuid4()
    for index, entry in enumerate(samples()):
        response = await save(client, entry, config, index)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["revision"] == index + 1
        assert result["feasibility"] == "not_assessed" and result["state"] == "saved_not_submitted"
    assert len(result["selections"]) == 4
    assert all(s["option_revision"] == 1 and s["current"] for s in result["selections"])
    # Recreate the owning app/pool, not an in-memory repository.
    restarted = create_app(Settings(service_name="catalog", database_url=access.runtime_url, modules_path=MODULES))
    async with restarted.router.lifespan_context(restarted):
        next(m for m in restarted.state.modules if m.id == "L10.options-color").load("dependencies.py:clients")(
            restarted
        )
        await restarted.state.l10_clients["identity"].aclose()
        restarted.state.l10_clients["identity"] = DependencyClient(
            "identity", "http://identity", transport=httpx.MockTransport(identity)
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://catalog") as second:
            loaded = await second.get(f"{ROOT}/configurations/{config}", headers=headers())
            assert loaded.json() == result
    async with app.state.pool.acquire() as tx:
        events = await tx.fetch("SELECT envelope FROM outbox")
        assert len(events) == 2 * len(samples())
        assert all("reference_ids" not in e["envelope"] and "Sample" not in e["envelope"] for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token,status",
    [("buyer", 403), ("wrong-org", 403), ("no-grant", 403), ("stock-only", 403), ("invalid", 403), ("offline", 503)],
)
async def test_brand_permissions_are_current_and_org_scoped(env, token, status):
    app, client, _ = env
    response = await publish(client, samples()[0], token=token)
    assert response.status_code == status, response.text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_options") == 0


@pytest.mark.asyncio
async def test_directory_never_admits_unonboarded_brand_and_outage_fails_closed(env):
    app, client, _ = env
    response = await client.get(ROOT + "/brands")
    assert [b["organization_id"] for b in response.json()["items"]] == [str(BRAND)]
    assert (await publish(client, samples()[0], brand=OTHER_BRAND)).status_code == 403
    await populate(client)
    await app.state.l10_clients["directory"].aclose()
    app.state.l10_clients["directory"] = DependencyClient(
        "directory", "http://directory", transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    assert (await save(client, samples()[0], uuid4())).status_code == 503
    assert (await client.get(f"{ROOT}/brands/{BRAND}")).status_code == 503
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_configurations") == 0


@pytest.mark.asyncio
async def test_duplicate_race_and_stale_config_do_not_duplicate_events(env):
    app, client, _ = env
    await populate(client)
    config, key = uuid4(), uuid4().hex
    first, second = await asyncio.gather(
        save(client, samples()[0], config, key=key), save(client, samples()[0], config, key=key)
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert (await save(client, samples()[1], config, key=key)).status_code == 409
    assert (await save(client, samples()[1], config, revision=0)).status_code == 409
    a, b = await asyncio.gather(
        save(client, samples()[1], config, revision=1), save(client, samples()[2], config, revision=1)
    )
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM outbox") == len(samples()) + 2
        assert await tx.fetchval("SELECT revision FROM l10_configurations WHERE id=$1", config) == 2


@pytest.mark.asyncio
async def test_cross_account_read_write_and_reference_ids_are_private(env):
    app, client, _ = env
    await populate(client)
    config = uuid4()
    assert (await save(client, samples()[0], config)).status_code == 200
    assert (await client.get(f"{ROOT}/configurations/{config}", headers=headers("other-buyer"))).status_code == 404
    assert (await save(client, samples()[1], config, revision=1, token="other-buyer")).status_code == 404
    assert (await client.get(f"{ROOT}/configurations", headers=headers("other-buyer"))).json()["items"] == []
    assert (await save(client, samples()[2], config, revision=1, reference_ids=[str(uuid4())])).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"option_revision": 2},
        {"base_model": "foreign-model"},
        {"caliber": "tourbillon"},
        {"component": "strap"},
        {"option_id": str(uuid4())},
        {"brand_id": str(OTHER_BRAND)},
    ],
)
@pytest.mark.parametrize("entry_index", [0, 1, 2, 3])
async def test_unsupported_injected_or_foreign_options_cannot_be_saved(env, overrides, entry_index):
    app, client, _ = env
    await populate(client)
    response = await save(client, samples()[entry_index], uuid4(), **overrides)
    assert response.status_code == 409, response.text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_configurations") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_index", [0, 1, 2, 3])
async def test_stale_and_unavailable_options_preserve_saved_snapshot(env, entry_index):
    _, client, _ = env
    await populate(client)
    entry = samples()[entry_index]
    config = uuid4()
    before = (await save(client, entry, config)).json()
    entry = copy.deepcopy(entry)
    entry["definition"].update(expected_revision=1, available=False)
    assert (await publish(client, entry)).status_code == 200
    assert (await save(client, samples()[entry_index], config, revision=1)).status_code == 409
    assert (await save(client, entry, config, revision=1, option_revision=2)).status_code == 409
    loaded = (await client.get(f"{ROOT}/configurations/{config}", headers=headers())).json()
    assert loaded["revision"] == 1
    assert loaded["selections"][0]["definition"] == before["selections"][0]["definition"]
    assert loaded["selections"][0]["current"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,details",
    [
        ("color", {"unsupported_coating": "anything"}),
        ("material", {"construction": "plating", "material": {"en": "Gold", "ar": "ذهب"}, "grade": "18K"}),
        ("dial", {"provenance": "forged"}),
        ("sophistication", {"conversion": "tourbillon"}),
    ],
)
async def test_undefined_option_definitions_are_rejected(env, kind, details):
    app, client, _ = env
    entry = copy.deepcopy(next(s for s in samples() if s["kind"] == kind))
    entry["definition"]["details"] = details
    response = await publish(client, entry)
    assert response.status_code == 422, response.text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_options") == 0


def png(width=1, height=1, pixels=b"\x00\xff\xff\xff"):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


@pytest.mark.asyncio
async def test_private_png_reference_is_authorized_bound_and_idempotent(env):
    app, client, _ = env
    await populate(client)
    config = uuid4()
    await save(client, samples()[0], config)
    data = png()
    key = uuid4().hex
    path = f"{ROOT}/configurations/{config}/references"
    response = await client.post(path, headers={**headers(key=key), "Content-Type": "image/png"}, content=data)
    assert response.status_code == 200, response.text
    reference = response.json()["id"]
    retry = await client.post(path, headers={**headers(key=key), "Content-Type": "image/png"}, content=data)
    assert retry.json() == response.json()
    resumed = await client.get(f"{ROOT}/configurations/{config}", headers=headers())
    assert resumed.json()["reference_ids"] == [reference]  # Uploaded, not yet attached, survives reload.
    assert all(not selected["reference_ids"] for selected in resumed.json()["selections"])
    private = await client.get(path + "/" + reference, headers=headers())
    assert private.content == data and private.headers["cache-control"] == "no-store"
    assert (await client.get(path + "/" + reference, headers=headers("other-buyer"))).status_code == 404
    assert (await client.get(path + "/" + reference)).status_code == 401
    foreign = uuid4()
    await save(client, samples()[0], foreign)
    assert (await save(client, samples()[2], foreign, revision=1, reference_ids=[reference])).status_code == 422
    selected = await save(client, samples()[2], config, revision=1, reference_ids=[reference])
    assert selected.status_code == 200, selected.text
    dial = next(s for s in selected.json()["selections"] if s["kind"] == "dial")
    assert dial["reference_ids"] == [reference]
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_references") == 1
        assert reference not in str(await tx.fetch("SELECT envelope FROM outbox"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data", [b'<svg onload="alert(1)"></svg>', b"bad", png(2049), png(pixels=b"\x00" * 10000), png() + b"<script>"]
)
async def test_unsafe_references_rejected_without_storage(env, data):
    app, client, _ = env
    await populate(client)
    config = uuid4()
    await save(client, samples()[0], config)
    response = await client.post(
        f"{ROOT}/configurations/{config}/references", headers={**headers(), "Content-Type": "image/png"}, content=data
    )
    assert response.status_code == 422, response.text
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_references") == 0


@pytest.mark.asyncio
async def test_named_package_cannot_claim_arbitrary_complication_conversion(env):
    _, client, _ = env
    entry = copy.deepcopy(samples()[3])
    entry["definition"]["details"]["interventions"] = [{"en": "Convert to tourbillon", "ar": "تحويل إلى توربيون"}]
    assert (await publish(client, entry)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 1.5, -1, 2147483648])
async def test_revision_boundaries_and_types_are_not_coerced(env, value):
    _, client, _ = env
    await populate(client)
    response = await save(client, samples()[0], uuid4(), revision=value)
    assert response.status_code == 422
    assert "1.5" not in response.text


@pytest.mark.asyncio
async def test_exact_revision_read_rejects_before_and_after_but_accepts_equal(env):
    _, client, _ = env
    await populate(client)
    config = uuid4()
    await save(client, samples()[0], config)
    await save(client, samples()[1], config, revision=1)
    for revision, expected in [(1, 409), (2, 200), (3, 409)]:
        response = await client.get(f"{ROOT}/configurations/{config}?expected_revision={revision}", headers=headers())
        assert response.status_code == expected


@pytest.mark.asyncio
async def test_material_plating_preserves_substrate_and_units(env):
    _, client, _ = env
    entry = copy.deepcopy(samples()[1])
    entry["definition"]["details"].update(
        construction="plating", substrate={"en": "Steel", "ar": "فولاذ"}, thickness_micrometers=5
    )
    assert (await publish(client, entry)).status_code == 200
    config = uuid4()
    result = (await save(client, entry, config)).json()
    details = result["selections"][0]["definition"]["details"]
    assert details["construction"] == "plating" and details["thickness_micrometers"] == 5
    assert details["substrate"] == {"en": "Steel", "ar": "فولاذ"}


@pytest.mark.asyncio
async def test_publication_replay_and_conflicting_write_are_atomic(env):
    app, client, _ = env
    entry = samples()[0]
    key = uuid4().hex
    first, second = await asyncio.gather(publish(client, entry, key=key), publish(client, entry, key=key))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    entry = copy.deepcopy(entry)
    entry["definition"]["available"] = False
    assert (await publish(client, entry, key=key)).status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_options") == 1
        assert await tx.fetchval("SELECT count(*) FROM outbox") == 1


@pytest.mark.asyncio
async def test_upload_budget_and_reference_limit_create_no_extra_rows(env):
    app, client, _ = env
    await populate(client)
    config = uuid4()
    await save(client, samples()[0], config)
    path = f"{ROOT}/configurations/{config}/references"
    assert (
        await client.post(path, headers={**headers(), "Content-Type": "image/png"}, content=b"X" * 1048577)
    ).status_code == 413
    for _ in range(3):
        assert (
            await client.post(path, headers={**headers(), "Content-Type": "image/png"}, content=png())
        ).status_code == 200
    assert (
        await client.post(path, headers={**headers(), "Content-Type": "image/png"}, content=png())
    ).status_code == 409
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_references") == 3


@pytest.mark.asyncio
async def test_sample_import_uses_authorized_operations_and_is_replay_safe(env, monkeypatch):
    app, _, _ = env
    seed = next(m for m in app.state.modules if m.id == "L10.options-color").load("fixtures.py:seed")
    monkeypatch.setenv("BT_OPTIONS_SAMPLE_BRAND", str(BRAND))
    monkeypatch.setenv("BT_OPTIONS_BRAND_TOKEN", "brand")

    def catalog_transport(dependency, origin, **kwargs):
        return DependencyClient(dependency, origin, transport=httpx.ASGITransport(app=app), **kwargs)

    monkeypatch.setitem(seed.__globals__, "DependencyClient", catalog_transport)
    await seed(app.state.settings)
    await seed(app.state.settings)
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM l10_options") == len(samples())
        assert await tx.fetchval("SELECT count(*) FROM outbox") == len(samples())
        assert await tx.fetchval("SELECT count(*) FROM l10_configurations") == 0


@pytest.mark.asyncio
async def test_catalog_contention_is_unavailable_and_same_operation_can_recover(env):
    app, client, _ = env
    await populate(client)
    config, key = uuid4(), uuid4().hex
    async with app.state.pool.acquire() as blocker:
        async with blocker.transaction():
            await blocker.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"l10-brand:{BRAND}")
            response = await save(client, samples()[0], config, key=key)
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "storage_unavailable"
    recovered = await save(client, samples()[0], config, key=key)
    assert recovered.status_code == 200 and recovered.json()["revision"] == 1
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval("SELECT count(*) FROM outbox") == len(samples()) + 1


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', [
    {'state':'revoked'}, {'kind':'dealer'}, {'platform_onboarded':False},
    {'authenticated_business':False}, {'capabilities':['servicing']},
])
async def test_current_business_authority_overrules_a_stale_directory(env, policy):
    app, client, _ = env
    await populate(client)
    config = uuid4()
    saved = (await save(client, samples()[0], config)).json()
    def transport(request):
        if request.url.path == '/v1/businesses':
            return httpx.Response(200, json={'items':[business(**policy)]})
        return identity(request)
    await app.state.l10_clients['identity'].aclose()
    app.state.l10_clients['identity'] = DependencyClient('identity','http://identity',transport=httpx.MockTransport(transport))
    assert (await client.get(ROOT+'/brands')).json()['items'] == []
    assert (await save(client, samples()[1], config, revision=1)).status_code == 409
    assert (await client.get(f'{ROOT}/configurations/{config}',headers=headers())).json() == saved


@pytest.mark.asyncio
async def test_business_read_outage_does_not_grant_from_cached_directory_claims(env):
    app, client, _ = env
    await populate(client)
    def transport(request):
        if request.url.path == '/v1/businesses':
            return httpx.Response(503)
        return identity(request)
    await app.state.l10_clients['identity'].aclose()
    app.state.l10_clients['identity'] = DependencyClient('identity','http://identity',transport=httpx.MockTransport(transport))
    assert (await client.get(ROOT+'/brands')).status_code == 503
    assert (await save(client, samples()[0], uuid4())).status_code == 503
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM l10_configurations') == 0


@pytest.mark.asyncio
async def test_sample_business_marker_cannot_be_hidden_by_directory_metadata(env):
    app, client, _ = env
    def transport(request):
        payload = directory(request).json()
        payload['items'][0]['sample'] = False
        return httpx.Response(200,json=payload)
    await app.state.l10_clients['directory'].aclose()
    app.state.l10_clients['directory'] = DependencyClient('directory','http://directory',transport=httpx.MockTransport(transport))
    response = await client.get(ROOT+'/brands')
    assert response.json()['items'][0]['sample'] is True
