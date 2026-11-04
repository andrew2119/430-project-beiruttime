from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from bt_bulkheads import DependencyClient
from bt_runtime.modules import discover

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def workspace():
    root = Path("/workspace-module")
    if not root.exists():
        root = Path(__file__).resolve().parents[4] / "services/communications/modules/seller-workspace"
    module = discover(root)[0]
    app = FastAPI()
    app.include_router(module.load("routes.py:router"))
    app.middleware("http")(lambda request, call_next: context(request, call_next))
    org, other, subject = uuid4(), uuid4(), uuid4()
    state = {
        "fail": set(),
        "org": None,
        "authorized_org": str(org),
        "auctions": [
            {
                "id": str(uuid4()),
                "listing_id": str(uuid4()),
                "current_minor": 18000,
                "currency": "USD",
                "accepted_sequence": 3,
                "status": "live",
                "reserve_minor": 99999,
            }
        ],
        "sales": [
            {
                "id": str(uuid4()),
                "watch_id": str(uuid4()),
                "seller_id": str(subject),
                "organization_id": None,
                "state": "awaiting_payment",
                "revision": 1,
                "deadline": "2026-11-04T08:00:00+00:00",
            },
            {
                "id": str(uuid4()),
                "watch_id": str(uuid4()),
                "seller_id": str(other),
                "organization_id": None,
                "state": "awaiting_payment",
                "revision": 1,
                "deadline": "2026-11-04T08:00:00+00:00",
            },
        ],
    }

    async def remote(request):
        if request.url.host in state["fail"]:
            return httpx.Response(503)
        if request.url.host == "identity":
            if request.headers.get("Authorization") != "Bearer signed-in":
                return httpx.Response(401)
            return httpx.Response(
                200,
                json={
                    "actor": {"subject_id": str(subject), "organization_id": state["org"], "session_id": "workspace"},
                    "roles": ["buyer"],
                    "permissions": [],
                    "organizations": [str(org)],
                    "organization_grants": [
                        {
                            "organization_id": str(org),
                            "roles": ["dealer"],
                            "permissions": ["business.stock.write", "identity.listings.publish"],
                        }
                    ],
                },
            )
        if request.url.host == "catalog":
            return httpx.Response(200, json={"items": [{"id": "own-draft"}], "next_cursor": None})
        if request.url.host == "auction":
            assert request.url.path == "/v1/seller/auctions"
            return httpx.Response(200, json={"items": state["auctions"]})
        if request.url.host == "orders":
            assert request.url.path == "/v1/orders"
            return httpx.Response(200, json={"items": state["sales"]})
        return httpx.Response(404)

    clients = {
        name: DependencyClient(name, f"http://{name}", transport=httpx.MockTransport(remote))
        for name in ("identity", "catalog", "orders", "auction")
    }
    app.state.seller_workspace_clients = clients
    from bt_contracts_core.errors import AccessDenied, PublicError
    from fastapi.responses import JSONResponse

    @app.exception_handler(AccessDenied)
    async def denied(request, exc):
        return JSONResponse({"code": "forbidden"}, status_code=403)

    @app.exception_handler(PublicError)
    async def public(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://communications") as client:
        yield SimpleNamespace(client=client, state=state, org=str(org), other=str(other))
    for client in clients.values():
        await client.aclose()


async def context(request, call_next):
    request.state.request_id = "workspace-test"
    return await call_next(request)


async def test_workspace_reads_actual_sections_without_inventing_payout(workspace):
    response = await workspace.client.get("/v1/seller/workspace", headers={"Authorization": "Bearer signed-in"})
    assert response.status_code == 200
    data = response.json()
    assert data["listings"]["data"]["items"] == [{"id": "own-draft"}]
    assert data["sales"]["data"]["items"][0]["state"] == "awaiting_payment"
    assert len(data["sales"]["data"]["items"]) == 1
    assert data["bids"]["data"]["items"][0]["accepted_sequence"] == 3
    assert "reserve_minor" not in data["bids"]["data"]["items"][0]
    assert data["payout"]["status"] == "not_available"


async def test_optional_outage_does_not_erase_other_cards(workspace):
    workspace.state["fail"] = {"auction"}
    data = (await workspace.client.get("/v1/seller/workspace", headers={"Authorization": "Bearer signed-in"})).json()
    assert data["bids"]["status"] == "unavailable"
    assert data["listings"]["status"] == "available" and data["sales"]["status"] == "available"


async def test_identity_outage_is_fail_closed(workspace):
    workspace.state["fail"] = {"identity"}
    assert (
        await workspace.client.get("/v1/seller/workspace", headers={"Authorization": "Bearer signed-in"})
    ).status_code == 503
    assert (await workspace.client.get("/v1/seller/workspace")).status_code == 401


async def test_expired_token_remains_refreshable_in_selected_organization(workspace):
    for path in ("/v1/seller/workspace", f"/v1/seller/workspace?organization_id={workspace.org}"):
        answer = await workspace.client.get(path, headers={"Authorization": "Bearer expired"})
        assert answer.status_code == 401


async def test_business_grants_do_not_union_between_organizations(workspace):
    workspace.state["org"] = workspace.other
    assert (
        await workspace.client.get("/v1/seller/workspace", headers={"Authorization": "Bearer signed-in"})
    ).status_code == 403
