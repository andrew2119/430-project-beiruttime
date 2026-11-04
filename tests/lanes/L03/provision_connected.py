"""Provision restricted, uniquely named local proof databases, not domain data.

Run in a short-lived Python test image with TEST_DATABASE_ADMIN_URL and /out
bound to this lane's ignored artifacts directory. Does not grant any user role
or create any identity, listing, financial or inspection fact.
"""

import asyncio
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit, urlunsplit, quote
from uuid import uuid4
import asyncpg


async def main():
    target = Path("/out/connected-databases.key")
    if target.exists():
        raise SystemExit("Existing isolated proof credentials preserved")
    parsed = urlsplit(os.environ["TEST_DATABASE_ADMIN_URL"])
    if parsed.hostname not in ("postgres", "localhost", "127.0.0.1") or parsed.path != "/postgres":
        raise SystemExit("Only the local maintenance database is allowed")
    admin = await asyncpg.connect(os.environ["TEST_DATABASE_ADMIN_URL"])
    databases = {}
    try:
        for domain in ("identity", "catalog", "pricing", "orders", "communications"):
            name = "bt_l03_" + domain.replace("-", "_") + "_" + uuid4().hex
            owner, runtime = name + "_owner", name
            passwords = {role: secrets.token_urlsafe(24) for role in (owner, runtime)}
            for role, password in passwords.items():
                await admin.execute(
                    await admin.fetchval(
                        "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', $1::text,$2::text)",
                        role,
                        password,
                    )
                )
            await admin.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
            setup = await asyncpg.connect(urlunsplit(parsed._replace(path="/" + name)))
            try:
                await setup.execute(f'''REVOKE ALL ON DATABASE "{name}" FROM PUBLIC;
                  GRANT CONNECT ON DATABASE "{name}" TO "{runtime}";
                  REVOKE ALL ON SCHEMA public FROM PUBLIC;
                  ALTER SCHEMA public OWNER TO "{owner}";
                  GRANT USAGE ON SCHEMA public TO "{runtime}";
                  ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public
                    GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}";
                  ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public
                    GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}";''')
            finally:
                await setup.close()

            def url(role):
                return urlunsplit(
                    parsed._replace(
                        netloc=f"{role}:{quote(passwords[role])}@{parsed.hostname}:{parsed.port or 5432}",
                        path="/" + name,
                    )
                )

            databases[domain] = {"name": name, "owner": url(owner), "runtime": url(runtime)}
            # Persist each acknowledged namespace for explicit cleanup if interrupted.
            target.write_text(json.dumps(databases))
            target.chmod(0o600)
        print("Provisioned five isolated restricted database namespaces; no domain data created")
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
