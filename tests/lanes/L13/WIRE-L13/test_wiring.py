"""Pure discovery and registration checks; no external connections."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUNTIME = ROOT / "services/orders/runtime"
spec = importlib.util.spec_from_file_location("orders_bootstrap", RUNTIME / "service_app/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

from bt_runtime.modules import discover  # noqa: E402
from bt_runtime.app.db import migration_steps  # noqa: E402
from bt_runtime.app.settings import Settings  # noqa: E402


def test_all_lane_boundaries_and_missing_fragments(tmp_path):
    assert discover(tmp_path / "missing") == []
    for lane in range(26):
        leaf = tmp_path / f"lane{lane}"
        leaf.mkdir()
        (leaf / "module.json").write_text(json.dumps({"version": 1, "id": f"L{lane:02}.sample"}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(discover, [tmp_path, tmp_path]))
    assert results[0] == results[1]
    assert len(results[0]) == 26
    (tmp_path / "lane25/module.json").write_text('{"version":1,"id":"L26.sample"}')
    with pytest.raises(ValueError, match="Invalid module"):
        discover(tmp_path)


def test_duplicate_module_denied(tmp_path):
    for name in ("first", "second"):
        leaf = tmp_path / name
        leaf.mkdir()
        (leaf / "module.json").write_text('{"version":1,"id":"L13.sample"}')
    with pytest.raises(ValueError, match="Duplicate module"):
        discover(tmp_path)


def test_full_additive_migration_plan():
    modules_path = ROOT / "services/orders/modules"
    steps = migration_steps(modules_path)
    names = [step[0] for step in steps]
    assert len(names) == len(set(names))
    assert names.index("L08.allocation/L08_0001_allocation.sql") < names.index(
        "L13.allocation/L13_0001_commitment.sql"
    )
    assert names.index("L13.allocation/L13_0003_notified_windows.sql") < names.index(
        "L13.allocation/L13_0004_quote_commitments.sql"
    )
    assert {module.id for module in discover(modules_path)} == {
        "L08.allocation", "L13.allocation", "L13.journal", "L13.payments"
    }


def test_service_identity_and_empty_application(tmp_path):
    app = bootstrap.create_app(Settings(database_url="unused", service_name="orders", modules_path=tmp_path))
    assert app.state.modules == []
    with pytest.raises(ValueError, match="service identity"):
        bootstrap.create_app(Settings(database_url="unused", service_name="catalog", modules_path=tmp_path))


def test_public_gateway_remains_bounded_and_internal_receipts_private():
    source = (ROOT / "web/registrations/L13.ts").read_text()
    assert source.count("{maxBodyBytes:65536,maxResponseBytes:262144,service:") == 14
    assert "/internal/" not in source
    assert "/callbacks/" not in source
    assert source.count("id:'l13-auction-winner'") == 1


def test_service_identity_and_empty_app(tmp_path):
    app = bootstrap.create_app(Settings(service_name="orders", database_url="unused", modules_path=tmp_path))
    assert app.state.settings.service_name == "orders"
    assert app.state.modules == []
    with pytest.raises(ValueError, match="service identity"):
        bootstrap.create_app(Settings(service_name="catalog", database_url="unused", modules_path=tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency", ["identity", "pricing", "catalog", "communications"])
async def test_dependency_timeout_and_circuit_remain_unavailable(dependency):
    import asyncio
    import httpx
    from bt_bulkheads import DependencyClient, Unavailable

    async def delayed(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"state": "confirmed"})

    client = DependencyClient(dependency, "http://source", timeout=0.005, concurrency=1,
                              failure_threshold=1, transport=httpx.MockTransport(delayed))
    try:
        result = await client.request("GET", "/internal/v1/current")
        assert isinstance(result, Unavailable)
        assert result.reason == "timeout"
        result = await client.request("GET", "/internal/v1/current")
        assert isinstance(result, Unavailable)
        assert result.reason == "circuit_open"
    finally:
        await client.aclose()


def test_contract_packaging_accepts_all_fragments_and_rejects_escape(tmp_path):
    spec = importlib.util.spec_from_file_location("orders_packaging", RUNTIME / "package_contracts.py")
    packaging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaging)
    registrations = tmp_path / "contracts/registrations"
    registrations.mkdir(parents=True)
    source = tmp_path / "packages/contracts-orders/allocation"
    source.mkdir(parents=True)
    (source / "v3.py").write_text('VERSION = 3\n')
    for lane in range(26):
        data = {"version": 1, "lane": f"L{lane:02}", "contracts": []}
        (registrations / f"L{lane:02}.json").write_text(json.dumps(data))
    data["contracts"] = [{"namespace": "orders.sample.v3", "path": "packages/contracts-orders/allocation"}]
    (registrations / "L25.json").write_text(json.dumps(data))
    destination = tmp_path / "output"
    packaging.package(tmp_path, destination)
    assert (destination / "bt_contracts/orders/allocation/v3.py").read_text() == 'VERSION = 3\n'
    data["contracts"][0]["path"] = "../outside"
    (registrations / "L25.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        packaging.discover(tmp_path)


def test_actual_routes_are_registered_once(monkeypatch):
    import sys
    from types import ModuleType

    for name, relative in (
        ("bt_contracts", "packages"),
        ("bt_contracts.orders", "packages/contracts-orders"),
        ("service_app", "services/orders/runtime/service_app"),
    ):
        namespace = ModuleType(name)
        namespace.__path__ = [str(ROOT / relative)]
        monkeypatch.setitem(sys.modules, name, namespace)
    app = bootstrap.create_app(Settings(service_name="orders", database_url="unused",
                                        modules_path=ROOT / "services/orders/modules"))
    routes = [(method, route.path) for route in app.routes for method in getattr(route, "methods", [])]
    assert len(routes) == len(set(routes))
    for method, path in (
        ("POST", "/internal/v3/payment-notices"),
        ("POST", "/v1/exact-reservations"),
        ("GET", "/v1/orders/{order_id}/checkout"),
        ("POST", "/v1/reservations"),
        ("GET", "/v1/operations/{operation_id}"),
    ):
        assert routes.count((method, path)) == 1


def test_operation_lookup_and_deterministic_outcomes():
    manifest = json.loads((ROOT / "contracts/registrations/L13.json").read_text())
    cases = json.loads((Path(__file__).parent / "outcomes.v1.json").read_text())
    assert {case["scenario"] for case in cases} == {"success", "denied", "stale", "lost_response"}
    for case in cases:
        assert case["sample"] is True
        result = case["result"]
        schema = manifest["outcome_schema"]
        assert set(result) == set(schema["required"])
        for field, rule in schema["properties"].items():
            value = result[field]
            if "const" in rule:
                assert value == rule["const"]
            elif "enum" in rule:
                assert value in rule["enum"]
            elif rule["type"] == "integer":
                assert type(value) is int and value >= rule["minimum"]
            elif rule["type"] == "string":
                assert isinstance(value, str)
            else:
                assert value is None or isinstance(value, str)
    assert len({case["result"]["operation_id"] for case in cases}) == 1
    assert cases[-1]["result"]["state"] == "pending"
    assert cases[-1]["result"]["next_actor"] == "operator"
    assert manifest["runtime"]["operations"]["payment_notice"]["producer"] == "communications"
    assert "communications-order-timeline" not in manifest["runtime"]["destinations"]["enabled"]


def test_duplicate_route_rejected(tmp_path):
    leaf = tmp_path / "sample"
    leaf.mkdir()
    (leaf / "routes.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n'
        '@router.get("/health/live")\ndef duplicate():\n    return {}\n'
    )
    (leaf / "module.json").write_text(json.dumps({
        "version": 1, "id": "L13.sample", "routes": ["routes.py:router"]
    }))
    with pytest.raises(ValueError, match="Duplicate route"):
        bootstrap.create_app(Settings(service_name="orders", database_url="unused", modules_path=tmp_path))


@pytest.mark.asyncio
async def test_payment_notice_subscription_gate(monkeypatch):
    import httpx
    import sys
    from types import ModuleType, SimpleNamespace
    from bt_bulkheads import Unavailable

    monkeypatch.syspath_prepend(str(RUNTIME))
    for name, relative in (
        ("bt_contracts", "packages"),
        ("bt_contracts.orders", "packages/contracts-orders"),
    ):
        namespace = ModuleType(name)
        namespace.__path__ = [str(ROOT / relative)]
        monkeypatch.setitem(sys.modules, name, namespace)
    from service_app import orders_dependencies

    app = SimpleNamespace(state=SimpleNamespace())
    dependencies = orders_dependencies.clients(app)
    client = dependencies["communications"]
    sent = []

    async def receive(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    await client.client.aclose()
    client.client = httpx.AsyncClient(base_url="http://communications", transport=httpx.MockTransport(receive))
    event = {"id": "stable-notice-reference", "type": "orders.payment-action-required.v3"}
    try:
        for _ in range(2):
            result = await client.request("POST", "/internal/v1/inbox/events", json=event)
            assert isinstance(result, Unavailable)
        assert sent == []
        assert event["id"] == "stable-notice-reference"
        old_event = {"type": "orders.reservation-created.v1"}
        result = await client.request("POST", "/internal/v1/inbox/events", json=old_event)
        assert result.status_code == 200
        assert sent == [old_event]
        manifest = json.loads((ROOT / "contracts/registrations/L13.json").read_text())
        assert "communications:orders.payment-action-required.v3" in manifest["runtime"]["destinations"]["pending"]
    finally:
        for dependency in dependencies.values():
            await dependency.aclose()
