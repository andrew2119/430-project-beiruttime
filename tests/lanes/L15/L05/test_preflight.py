from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from bt_contracts.catalog.listings.v1 import Publish
from bt_contracts_core.errors import PublicError
from modules.listings import routes
from modules.listings.revisions import routes as revisions


@pytest.mark.asyncio
@pytest.mark.parametrize("module,code", [(routes, "publication_review_denied"), (routes, "publication_review_pending"), (revisions, "publication_review_denied")])
async def test_initial_review_failure_never_freezes_source(monkeypatch, module, code):
    listing = UUID("00000000-0000-4000-8000-000000000001")
    owner = UUID("00000000-0000-4000-8000-000000000003")
    facts = dict(brand="Sample", model="Watch", reference="Reference", year=2020,
                 condition="Declared wear", location="Beirut", price_minor=500000,
                 component_wear={"case": "Light wear"}, modified=False,
                 ownership_confirmed=True)
    row = dict(id=listing, physical_watch_id=UUID("00000000-0000-4000-8000-000000000002"),
               owner_subject_id=owner, organization_id=None, revision=1, facts=facts,
               status="draft" if module is routes else "published", is_hidden=False,
               photo_ids=[UUID("00000000-0000-4000-8000-000000000004")], fee_snapshot=None)
    calls = []

    class Connection:
        async def fetchrow(self, sql, *args):
            calls.append(sql)
            return row if "FROM catalog_listings" in sql else None

    @asynccontextmanager
    async def acquire():
        yield Connection()

    request = SimpleNamespace(state=SimpleNamespace(), headers={"If-Match": "1", "Idempotency-Key": "publication-001"},
                              app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=owner, organization_id=None))

    async def principal(_):
        return person

    async def quote(*args, **kwargs):
        return {}

    async def review(*args, **kwargs):
        raise PublicError(code, "Review required", status=409 if code.endswith("denied") else 503)

    def unexpected_write(*args, **kwargs):
        pytest.fail("A denied initial review must not acquire a mutation transaction")

    monkeypatch.setattr(module, "principal", principal)
    monkeypatch.setattr(module, "seller_scope", lambda *args: None)
    monkeypatch.setattr(module, "assert_owner", lambda actual, actor: None)
    monkeypatch.setattr(module, "check_publication", review)
    monkeypatch.setattr(module, "unit_of_work", unexpected_write)
    if module is routes:
        monkeypatch.setattr(module, "upstream", quote)
        body = Publish(fee_quote_id=UUID("00000000-0000-4000-8000-000000000005"), rules_version="sample-v1")
        action = routes.publish(listing, body, request)
    else:
        body = revisions.Revise(facts={**facts, "reference": "Changed identity"}, reason="Correct reference")
        action = revisions.revise(listing, body, request)
    with pytest.raises(PublicError) as result:
        await action
    assert result.value.code == code
    assert all(sql.startswith("SELECT") for sql in calls)

@pytest.mark.asyncio
@pytest.mark.parametrize("recorded_denial,orders_started", [(True, True), (False, True), (False, False)])
async def test_retained_abort_settles_before_review_without_new_preparation(monkeypatch, recorded_denial, orders_started):
    operation = UUID("00000000-0000-4000-8000-000000000006")
    row = {"id": UUID("00000000-0000-4000-8000-000000000001"), "physical_watch_id": UUID("00000000-0000-4000-8000-000000000002")}
    op = {"id": operation, "listing_id": row["id"], "status": "pending",
          "result": {"status": "denied"} if recorded_denial else None,
          "orders_started": orders_started, "auction_prepared": True, "auction_dispatched": False}

    class Connection:
        async def fetchrow(self, sql, *args):
            return op if "catalog_listing_edits" in sql else row

    @asynccontextmanager
    async def acquire():
        yield Connection()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))

    async def principal(_):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=operation))

    async def review(*args):
        pytest.fail("Reconciliation must precede review admission")

    async def remote(request, service, method, path):
        assert service == "auction"
        assert path == f"/internal/v3/listing-edits/{operation}/{'abort' if recorded_denial else 'reconcile'}"
        return {"phase": "aborted"}

    async def settled(request, actual_op, actual_row, result):
        assert actual_op is op and actual_row is row
        assert result["phase"] == "aborted"
        return {"status": "denied"}

    monkeypatch.setattr(revisions, "principal", principal)
    monkeypatch.setattr(revisions, "seller_scope", lambda *args: None)
    monkeypatch.setattr(revisions, "assert_owner", lambda *args: None)
    monkeypatch.setattr(revisions, "check_publication", review)
    monkeypatch.setattr(revisions, "held_request", remote)
    monkeypatch.setattr(revisions, "finish_aborted", settled)
    assert await revisions.resume(request, operation) == {"status": "denied"}


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_review_denial_requests_remote_abort_even_before_preparation(monkeypatch, confirmed):
    operation = UUID("00000000-0000-4000-8000-000000000006")
    row = {"id": UUID("00000000-0000-4000-8000-000000000001"), "physical_watch_id": UUID("00000000-0000-4000-8000-000000000002")}
    op = {"id": operation, "listing_id": row["id"], "status": "pending", "result": None,
          "facts": {}, "base_revision": 1, "orders_started": False, "auction_prepared": False, "auction_dispatched": False}

    class Connection:
        async def execute(self, sql, *args):
            op["result"] = {"status": "denied", "code": "publication_review_denied"}

        async def fetchrow(self, sql, *args):
            return op if "catalog_listing_edits" in sql else row

    @asynccontextmanager
    async def acquire():
        yield Connection()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=acquire))))

    async def principal(_):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=operation))

    async def review(*args):
        raise PublicError("publication_review_denied", "Review denied", status=409)

    async def remote(request, service, method, path, **kwargs):
        assert kwargs["json"]["operation_id"] == str(operation)
        assert kwargs["json"]["reason"] == "publication_review_denied"
        assert service == "auction" and method == "POST"
        assert path == f"/internal/v3/listing-edits/{operation}/abort"
        if not confirmed:
            raise PublicError("edit_pending", "Reconcile retained edit", status=503)
        return {"phase": "aborted"}

    async def settled(request, actual_op, actual_row, result):
        assert actual_op is op and actual_row is row and result == {"phase": "aborted"}
        return {"status": "denied"}

    monkeypatch.setattr(revisions, "unit_of_work", lambda *args, **kwargs: acquire())
    monkeypatch.setattr(revisions, "principal", principal)
    monkeypatch.setattr(revisions, "seller_scope", lambda *args: None)
    monkeypatch.setattr(revisions, "assert_owner", lambda *args: None)
    monkeypatch.setattr(revisions, "check_publication", review)
    monkeypatch.setattr(revisions, "held_request", remote)
    monkeypatch.setattr(revisions, "finish_aborted", settled)
    if confirmed:
        assert await revisions.resume(request, operation) == {"status": "denied"}
    else:
        with pytest.raises(PublicError) as failure:
            await revisions.resume(request, operation)
        assert failure.value.code == "edit_pending"
        assert op["status"] == "pending"
        async def now_eligible(*args):
            pytest.fail("Retained abort must settle before fresh eligibility")
        monkeypatch.setattr(revisions, "check_publication", now_eligible)
        with pytest.raises(PublicError):
            await revisions.resume(request, operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["success", "denied", "stale", "lost_response", "wrong_operation"])
async def test_review_abort_requires_exact_terminal_acknowledgement(monkeypatch, case):
    import json
    from pathlib import Path

    fixture = json.loads((Path(__file__).resolve().parents[4] / "packages/contracts-catalog/listings/fixtures/revision-abort-v1.json").read_text())
    value = fixture.get(case)
    if case == "wrong_operation":
        value = {**fixture["success"], "operation_id": "different-operation"}
    row = {"id": UUID(fixture["request"]["listing_id"]), "physical_watch_id": UUID(fixture["request"]["watch_id"]), "revision": 1}
    op = {"id": UUID(fixture["request"]["operation_id"]), "status": "pending", "result": None,
          "base_revision": 1, "auction_protocol": 3, "orders_started": False, "auction_dispatched": False}
    writes = []

    class Connection:
        async def fetchrow(self, sql, *args):
            if sql.startswith("UPDATE"):
                writes.append(sql)
                op["status"] = "denied"
            return op

        async def execute(self, sql, *args):
            writes.append(sql)
            op["result"] = json.loads(args[1])

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield Connection()

    async def listing(*args):
        return row

    monkeypatch.setattr(revisions, "unit_of_work", transaction)
    monkeypatch.setattr(revisions, "lock_listing", listing)
    monkeypatch.setattr(revisions, "dto", lambda actual: {"revision": actual["revision"]})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    if case == "success":
        result = await revisions.finish_aborted(request, op, row, value)
        assert result["status"] == "denied"
        assert result["code"] == "publication_review_denied"
        assert op["result"] == result
        assert len(writes) == 2
    else:
        with pytest.raises(PublicError) as failure:
            await revisions.finish_aborted(request, op, row, value)
        assert failure.value.code == "edit_pending"
        assert not writes and op["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["success", "denied", "stale", "lost_response", "wrong_binding"])
async def test_publication_abort_unlocks_only_after_terminal_registration_receipt(monkeypatch, case):
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).resolve().parents[4] / "packages/contracts-catalog/listings/fixtures/publication-abort-v1.json").read_text())
    row = {"id": "listing-001", "physical_watch_id": "watch-001", "organization_id": None, "revision": 1, "status": "publication_pending"}
    op = {"id": "publication-001", "actor_id": "seller-001", "base_revision": 1, "review_denied": True}
    writes = []
    value = fixture.get(case)
    if case == "wrong_binding":
        value = {**fixture["success"], "watch_id": "other-watch"}

    class Connection:
        async def fetchrow(self, sql, *args):
            return row if "catalog_listings" in sql else op

        async def execute(self, sql, *args):
            writes.append(sql)

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield Connection()

    async def remote(request, service, method, path, **kwargs):
        assert service == "orders" and path == "/internal/v1/watches/registration-abort"
        assert kwargs["json"] == fixture["request"]
        assert kwargs["headers"]["Idempotency-Key"] == op["id"]
        return value

    monkeypatch.setattr(routes, "unit_of_work", transaction)
    monkeypatch.setattr(routes, "service_request", remote)
    monkeypatch.setattr(routes, "assert_owner", lambda *args: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    with pytest.raises(PublicError) as failure:
        await routes.settle_publication_review(request, row, op, None)
    assert failure.value.code == ("stale_revision" if case == "success" else "registration_pending")
    assert len(writes) == (2 if case == "success" else 0)
    if writes:
        assert "revision=revision+1" in writes[1]


@pytest.mark.asyncio
async def test_post_freeze_denial_is_durable_before_abort(monkeypatch):
    row = {"id": "listing", "revision": 1, "status": "publication_pending"}
    op = {"id": "operation", "base_revision": 1}
    writes = []

    class Connection:
        async def fetchrow(self, *args):
            return row

        async def execute(self, sql, *args):
            writes.append(sql)

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield Connection()

    async def denied(*args):
        raise PublicError("publication_review_denied", "Review denied", status=409)

    async def settle(*args):
        assert writes and "review_denied=true" in writes[0]
        raise PublicError("registration_pending", "Retry original operation", status=503)

    monkeypatch.setattr(routes, "check_publication", denied)
    monkeypatch.setattr(routes, "unit_of_work", transaction)
    monkeypatch.setattr(routes, "settle_publication_review", settle)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)))
    person = SimpleNamespace(actor=SimpleNamespace(subject_id="owner"))
    with pytest.raises(PublicError, match="registration_pending"):
        await routes.publication_review(request, row, op, person)
