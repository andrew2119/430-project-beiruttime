import json
from uuid import UUID

import httpx
import pytest
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover

from .test_listing_lifecycle import catalog_modules


def listing_module():
    return next(module for module in discover(catalog_modules()) if module.id == "L03.listings")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,category,upstream", [
    (503, "publication_review_pending", "publication_review_pending", "identity"),
    (503, "registration_pending", "registration_pending", None),
    (429, "not-a-known-code", "upstream", None),
])
async def test_publication_private_frame_projects_only_known_fields(status, code, category, upstream, monkeypatch, capsys):
    fixture = listing_module().load("fixtures.py:seed").__globals__
    body = {"error": {"code": code, "message": "untrusted-stderr-token", "details": {"cookie": "new-secret"}}}
    client = DependencyClient("catalog", "http://catalog", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body)))
    received = []

    def observe(response):
        received.append(fixture["catalog_publication_error_code"](response))

    try:
        result = await client.request("POST", "/v1/seller/listings/example/publish", observe_failure=observe)
    finally:
        await client.aclose()
    assert isinstance(result, Unavailable) and result.status_code == status and result.reason == "upstream"
    error = fixture["PublicationUnavailable"](result, received[0])
    monkeypatch.delenv("BT_DEMO_PRIVATE_DIAGNOSTICS", raising=False)
    error.emit_private_record()
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("BT_DEMO_PRIVATE_DIAGNOSTICS", "1")
    error.emit_private_record()
    captured = capsys.readouterr()
    assert captured.out == ""
    prefix = fixture["PUBLICATION_FAILURE_PREFIX"]
    assert captured.err.startswith(prefix)
    assert json.loads(captured.err[len(prefix):]) == {"category": category, "http_status": status, "upstream": upstream}
    assert str(error) == "Catalog publication unavailable; consult private diagnostics"


@pytest.mark.asyncio
async def test_publication_diagnostic_omits_caller_id_and_retains_typed_pending(monkeypatch, caplog, tmp_path):
    from service_app.catalog_dependencies import observe_publication_upstream

    caller_id = "caller_opaque_refresh_token_f047a0"
    expected = PublicError("publication_review_pending", "opaque-private-evidence", status=503)

    async def pending(listing_id, body, request):
        assert request.state.request_id == caller_id  # The runtime accepted a caller-chosen opaque value.
        publish.__globals__["publication_step"](request, "eligibility", "identity")
        observe_publication_upstream(request, "identity", httpx.Response(200))
        raise expected

    app, publish = publication_app(monkeypatch, caplog, tmp_path, pending)
    response = await request_publication(app, headers={"X-Request-ID": caller_id})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == expected.code
    record, = (record for record in caplog.records if record.msg == "catalog.publication.failed")
    assert record.fields == {"status": 503, "phase": "eligibility", "upstream": "identity",
                             "upstream_http_status": 200, "category": "publication_review_pending"}
    assert caller_id not in repr(record.__dict__)
    assert "opaque-private-evidence" not in repr(record.__dict__)


@pytest.mark.asyncio
async def test_policy_denial_is_runtime_403_and_not_a_publication_failure(monkeypatch, caplog, tmp_path):
    async def deny(listing_id, body, request):
        raise AccessDenied("Ownership differs")

    app, _ = publication_app(monkeypatch, caplog, tmp_path, deny)
    response = await request_publication(app)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert not any(record.msg == "catalog.publication.failed" for record in caplog.records)


def publication_app(monkeypatch, caplog, tmp_path, implementation):
    from service_app.catalog_dependencies import logger

    publish = listing_module().load("routes.py:publish")
    monkeypatch.setitem(publish.__globals__, "publish_listing", implementation)
    # Use the real request middleware and exception handlers, without service lifespan or SQL.
    app = create_app(Settings(service_name="catalog", database_url="postgresql://unused/unused", modules_path=tmp_path))
    app.add_api_route("/v1/seller/listings/{listing_id}/publish", publish, methods=["POST"])
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    return app, publish


async def request_publication(app, *, headers=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://catalog") as client:
        listing_id, quote_id = UUID(int=1), UUID(int=2)
        return await client.post(f"/v1/seller/listings/{listing_id}/publish", headers=headers,
                                 json={"fee_quote_id": str(quote_id), "rules_version": "usd-v2"})
