import json
import shutil
from pathlib import Path
import asyncpg
import pytest
from bt_runtime.app import db


@pytest.mark.asyncio
async def test_module_migrations_are_atomic_and_checksummed(database_url, database_owner_url, tmp_path):
    # Keep the already-applied Auction migration inventory while adding the proof module.
    for installed in Path('/app/modules').iterdir():
        if installed.is_dir():
            shutil.copytree(installed, tmp_path / installed.name)
    module = tmp_path/'proof'
    module.mkdir()
    registration = {'version':1,'id':'L01.migration-proof','migrations':['L01_0001_proof.sql','L01_0002_proof.sql']}
    (module/'module.json').write_text(json.dumps(registration))
    (module/'L01_0001_proof.sql').write_text('CREATE TABLE module_proof(id integer PRIMARY KEY);')
    (module/'L01_0002_proof.sql').write_text('NOT VALID SQL;')
    with pytest.raises(asyncpg.PostgresSyntaxError):
        await db.migrate(database_owner_url, tmp_path)
    pool=await db.create_pool(database_url)
    try:
        async with pool.acquire() as tx:
            assert await tx.fetchval("SELECT to_regclass('module_proof')") is None
        (module/'L01_0002_proof.sql').write_text('CREATE INDEX module_proof_id ON module_proof(id);')
        await db.migrate(database_owner_url, tmp_path)
        assert await db.ready(pool, tmp_path)
        (module/'L01_0001_proof.sql').write_text('CREATE TABLE changed_history(id integer);')
        with pytest.raises(RuntimeError, match='checksum'):
            await db.migrate(database_owner_url, tmp_path)
    finally:
        await pool.close()
