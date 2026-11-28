"""Current source bindings retain immutable independent revision history."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest
from bt_contracts.catalog.request_drafts.bindings import WatchBinding, AssignmentBinding
from bt_contracts_core.errors import AccessDenied, PublicError

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location(
    "request_bindings", ROOT / "services/catalog/modules/request-drafts/submission/bindings.py"
)
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)
pytest_plugins = ["bt_runtime.testing"]


@pytest.mark.asyncio
async def test_source_bindings_and_immutable_history(database_url, monkeypatch):
    pool = await asyncpg.create_pool(database_url)
    request_id, draft_id, buyer, brand, watch = [uuid4() for _ in range(5)]
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    producer = ["orders"]

    def service(request, allowed):
        if producer[0] not in allowed:
            raise AccessDenied("Wrong source")
        return producer[0]

    monkeypatch.setattr(routes, "service", service)
    try:
        async with pool.acquire() as tx:
            await tx.execute("INSERT INTO l08_request_drafts(id,owner_id,content) VALUES($1,$2,'{}')", draft_id, buyer)
            await tx.execute(
                "INSERT INTO catalog_customization_requests(id,draft_id,buyer_id,brand_id) VALUES($1,$2,$3,$4)",
                request_id, draft_id, buyer, brand,
            )
            await tx.execute(
                "INSERT INTO catalog_customization_revisions(request_id,revision,configuration_digest,"
                "configuration,content,actor_id,reason) VALUES($1,1,'test-digest','{}','{}',$2,'test submission')",
                request_id, buyer,
            )
        command = WatchBinding(operation_id=uuid4(), source_revision=1, expected_binding_revision=0,
                               request_revision=1, buyer_id=buyer, brand_id=brand, watch_id=watch)
        first = await routes.owned_watch(request_id, command, request)
        assert first["watch_id"] == str(watch) and first["recovery_operator_id"] is None
        assert await routes.owned_watch(request_id, command, request) == first
        with pytest.raises(PublicError, match="Source operation differs"):
            await routes.owned_watch(request_id, command.model_copy(update={"watch_id": uuid4()}), request)
        people = [uuid4() for _ in range(4)]
        assignment = AssignmentBinding(**{**command.model_dump(), "operation_id": uuid4(),
                                          "expected_binding_revision": 1},
                                       **dict(zip(("assessor_id", "approver_id", "quality_reviewer_id",
                                                   "recovery_operator_id"), people)))
        with pytest.raises(AccessDenied):
            await routes.assignment(request_id, assignment, request)
        producer[0] = "service-operations"
        with pytest.raises(AccessDenied):
            await routes.assignment(request_id, assignment.model_copy(update={"approver_id": people[0]}), request)
        second = await routes.assignment(request_id, assignment, request)
        assert second["binding_revision"] == 2 and second["recovery_operator_id"] == str(people[3])
        assert await routes.assignment(request_id, assignment, request) == second
        with pytest.raises(PublicError):
            await routes.assignment(request_id, assignment.model_copy(update={"operation_id": uuid4()}), request)
        producer[0] = "orders"
        third = await routes.owned_watch(request_id, command.model_copy(update={
            "operation_id": uuid4(), "source_revision": 2, "expected_binding_revision": 2, "watch_id": uuid4(),
        }), request)
        assert third["recovery_operator_id"] is None and third["assessor_id"] is None
        async with pool.acquire() as tx:
            assert await tx.fetchval("SELECT revision FROM catalog_customization_requests WHERE id=$1", request_id) == 1
            assert await tx.fetchval("SELECT count(*) FROM catalog_request_binding_history WHERE request_id=$1", request_id) == 3
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await tx.execute("DELETE FROM catalog_request_binding_history WHERE request_id=$1", request_id)
    finally:
        await pool.close()


@pytest.mark.parametrize("value", [True, 0, -1, 2147483648])
def test_source_revision_is_strict_and_bounded(value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WatchBinding(operation_id=uuid4(), source_revision=value, expected_binding_revision=0,
                     request_revision=1, buyer_id=uuid4(), brand_id=uuid4(), watch_id=uuid4())


def test_commands_reject_untyped_watch_reference():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WatchBinding(operation_id=uuid4(), source_revision=1, expected_binding_revision=0,
                     request_revision=1, buyer_id=uuid4(), brand_id=uuid4(), watch_id="test reference")
