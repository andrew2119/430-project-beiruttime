"""Private draft pagination and current personal scope."""

import importlib.util
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
from bt_contracts_core.errors import PublicError, AccessDenied

ROOT = Path(__file__).resolve().parents[4]
package = ModuleType("c07_drafts")
package.__path__ = [str(ROOT / "services/catalog/modules/request-drafts")]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("bt_contracts.catalog.request_drafts", ROOT / "packages/contracts-catalog/request-drafts/__init__.py", submodule_search_locations=[str(ROOT / "packages/contracts-catalog/request-drafts")])
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)
from c07_drafts import routes, dependencies  # noqa: E402


class DraftRows:
    def __init__(self, count):
        self.owner = uuid4()
        now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        self.rows = [{"id": UUID(int=i + 1), "owner_id": self.owner, "content": "{}", "revision": 1,
                      "updated_at": now - timedelta(seconds=i), "submitted_request_id": None}
                     for i in range(count)]

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self, **options):
        assert options == {"isolation": "repeatable_read", "readonly": True}
        yield

    async def fetchval(self, sql, *args):
        if "count(*)" in sql:
            assert "owner_id=$1" in sql and args == (self.owner,)
            return len(self.rows)
        assert "id=$1 AND owner_id=$2" in sql and args[1] == self.owner
        return any(row["id"] == args[0] for row in self.rows)

    async def fetch(self, sql, owner, before, limit):
        assert owner == self.owner and "owner_id=$1" in sql
        assert "ORDER BY updated_at DESC,id DESC LIMIT $3" in sql
        assert "(updated_at,id)<" in sql
        start = next((i + 1 for i, row in enumerate(self.rows) if row["id"] == before), 0)
        return self.rows[start:start + limit]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 1000])
async def test_complete_pagination_with_current_server_total(count):
    pool = DraftRows(count)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=pool.owner))
    before, seen = None, []
    while True:
        page = await routes.drafts(request, person, limit=37, before=before)
        assert page["total"] == count and len(page["items"]) <= 37
        seen.extend(row["id"] for row in page["items"])
        before = UUID(page["next_cursor"]) if page["next_cursor"] else None
        if before is None:
            break
    assert len(seen) == len(set(seen)) == count


@pytest.mark.asyncio
async def test_foreign_cursor_is_rejected():
    pool = DraftRows(1)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    person = SimpleNamespace(actor=SimpleNamespace(subject_id=pool.owner))
    with pytest.raises(PublicError) as error:
        await routes.drafts(request, person, limit=50, before=uuid4())
    assert error.value.code == "invalid_cursor"


@pytest.mark.asyncio
async def test_selected_business_scope_cannot_write_personal_drafts(monkeypatch):
    async def current(*args):
        return SimpleNamespace(roles=["buyer"], actor=SimpleNamespace(organization_id=uuid4()))
    monkeypatch.setattr(dependencies, "current_principal", current)
    monkeypatch.setattr(dependencies, "clients", lambda app: {"identity": object()})
    request = SimpleNamespace(headers={"Authorization": "Bearer sample"}, app=object(),
                              state=SimpleNamespace(request_id="sample"))
    with pytest.raises(AccessDenied):
        await dependencies.principal(request)
