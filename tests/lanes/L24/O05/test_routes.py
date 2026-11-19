import asyncio
import json

import pytest
from starlette.requests import Request

from services.orders.modules.custody.domain import Context
from services.orders.modules.custody.routes import build_router
from test_custody import command, custody as make_custody, proof


@pytest.fixture
def custody(tmp_path):
    return make_custody.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def inline_boundary(monkeypatch):
    # Pure route checks exercise decoding and dispatch without a running server.
    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr("starlette.concurrency.run_in_threadpool", invoke)


def request(custody, method, path, **kwargs):
    router = build_router(custody, lambda: Context("buyer", None))
    context = Context("buyer", None)
    if method == "GET":
        if "/operations/" in path:
            order, operation = path.split("/custody/")[1].split("/operations/")
            route = next(route for route in router.routes if route.name == "lookup")
            return route.endpoint(order, operation, context)
        route = next(route for route in router.routes if route.name == "read")
        return route.endpoint(path.rsplit("/", 1)[1], context)
    route = next(route for route in router.routes if route.name == "command")
    body = kwargs.get("content", json.dumps(kwargs.get("json")).encode())

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": method, "path": path, "headers": []}
    order = path.split("/custody/")[1].split("/")[0] if path.endswith("buyer-receipts") else None
    return asyncio.run(route.endpoint(Request(scope, receive), order, context))


def result(response):
    return json.loads(response.body)


def test_read_is_private_and_missing(custody):
    response = request(custody, "GET", "/v1/custody/order")
    assert response.status_code == 200 and result(response)["result"] is None
    assert response.headers["cache-control"] == "no-store"


def test_buyer_route_cannot_dispatch(custody):
    response = request(custody, "POST", "/v1/custody/order/buyer-receipts", json=command("dispatch"))
    assert response.status_code == 422
    assert custody.read(Context("buyer", None), "order") is None


def test_bounded_body(custody):
    response = request(custody, "POST", "/internal/v1/custody/commands", content=b"x" * 16385)
    assert response.status_code == 422


def test_receipt_and_lookup(custody):
    response = request(custody, "POST", "/v1/custody/order/buyer-receipts",
                       json=command("buyer_receipt", proof=proof()))
    assert response.status_code == 200
    lookup = request(custody, "GET", "/internal/v1/custody/order/operations/operation")
    assert result(lookup) == result(response)
    other = request(custody, "GET", "/internal/v1/custody/other/operations/operation")
    assert other.status_code == 403


def test_provider_timeout_never_confirms(custody):
    custody.provider.unavailable = True
    response = request(custody, "POST", "/internal/v1/custody/commands", json=command())
    assert response.status_code == 503 and result(response)["retry_same_operation"]
