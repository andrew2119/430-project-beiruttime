"""Orders sends required payment notices to the scoped Communications receiver."""

import json

import pytest


@pytest.mark.asyncio
async def test_payment_notice_subscription_preserves_producer_envelope(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from service_app import orders_dependencies, payment_notices

    order = {"id": uuid4(), "buyer_id": uuid4(), "revision": 2, "is_demo": False}
    event_id = uuid4()
    enqueue = AsyncMock()
    monkeypatch.setattr(payment_notices, "enqueue", enqueue)
    await payment_notices.ensure_payment_notice(SimpleNamespace(fetchval=AsyncMock(return_value=event_id)),
                                               order, "payment-test")
    _, envelope, subscriptions = enqueue.call_args.args
    assert subscriptions == ["communications"]
    assert (envelope.id, envelope.source, envelope.type) == (
        event_id, "orders", "orders.payment-action-required.v3")
    assert envelope.subject == str(order["id"])
    assert envelope.data == {
        "order_id": str(order["id"]), "buyer_id": str(order["buyer_id"]),
        "recipient_id": str(order["buyer_id"]), "revision": 2,
        "required": True, "sample": False, "simulated": True,
    }

    app = SimpleNamespace(state=SimpleNamespace())
    dependencies = orders_dependencies.clients(app)
    client = dependencies["communications"]
    sent = []

    async def receive(request):
        sent.append((request.url.path, json.loads(request.content), request.headers["Authorization"]))
        return httpx.Response(403 if len(sent) == 1 else 200)

    await client.client.aclose()
    client.client = httpx.AsyncClient(base_url="http://communications", transport=httpx.MockTransport(receive))
    event = envelope.model_dump(mode="json")
    headers = {"Authorization": "Bearer synthetic-service-test"}
    inbox = "/internal/v1/inbox/events"
    try:
        denied = await client.request("POST", inbox, json=event, headers=headers)
        assert denied.status_code == 403
        retried = await client.request("POST", inbox, json=event, headers=headers)
        assert retried.status_code == 200
        reservation = {"type": "orders.reservation-created.v1"}
        assert (await client.request("POST", inbox, json=reservation, headers=headers)).status_code == 200
        assert sent == [
            ("/internal/v3/payment-events", event, headers["Authorization"]),
            ("/internal/v3/payment-events", event, headers["Authorization"]),
            (inbox, reservation, headers["Authorization"]),
        ]
    finally:
        for dependency in dependencies.values():
            await dependency.aclose()
