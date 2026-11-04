import os
import asyncpg
import pytest


@pytest.mark.asyncio
async def test_runtime_roles_cannot_cross_databases_or_create_tables(database_runtime_url):
    url = os.environ.get("TEST_RUNTIME_URL")
    if not url:
        pytest.skip("TEST_RUNTIME_URL is required for role boundary proofs")
    runtime = await asyncpg.connect(url)
    try:
        assert not await runtime.fetchval("SELECT has_schema_privilege(current_user,'public','CREATE')")
        assert not await runtime.fetchval(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        )
    finally:
        await runtime.close()
    isolated = await asyncpg.connect(database_runtime_url)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await isolated.execute("CREATE TABLE forbidden_ddl(id integer)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await isolated.execute("DELETE FROM migration_ledger WHERE false")
    finally:
        await isolated.close()
    own = url.rsplit("/", 1)[1]
    databases = [
        "bt_identity",
        "bt_catalog",
        "bt_auction",
        "bt_pricing",
        "bt_orders",
        "bt_eligibility",
        "bt_trust",
        "bt_communications",
        "bt_service_ops",
        "postgres",
        "template1",
    ]
    for other in databases:
        if other == own:
            continue
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            conn = await asyncpg.connect(url.rsplit("/", 1)[0] + "/" + other)
            await conn.close()
