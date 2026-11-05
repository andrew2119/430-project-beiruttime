"""Isolated real Identity/Catalog/Directory proof. Run only through bt-heavy.

Keeps its own stack alive for browser checks, then stops (never removes) it.
Initial sample principals are confined to generated restricted databases. All
business/option/draft/submission mutations use actual service operations.
"""

import asyncio
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from uuid import uuid4

import asyncpg
import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "tests/lanes/L15/.artifacts"
PROJECT = "bt-l15-proof-9376f15f-" + uuid4().hex[:6]
COMPOSE = [
    "docker",
    "compose",
    "--project-name",
    PROJECT,
    "-f",
    str(ROOT / "tests/lanes/L15/compose.proof.yaml"),
]
ORIGIN = "http://127.0.0.1:3315"
LISTING_AUTHORITIES = '--listing-authorities' in sys.argv
SERVICES = ('identity','catalog','pricing','orders','auction') if LISTING_AUTHORITIES else ('identity','catalog','service-operations')
PORTS = (3315,8315,8415,8615,8715,8815) if LISTING_AUTHORITIES else (3315,8315,8415,8515)


def persist(path, value):
    path.write_text(json.dumps(value, indent=2))
    path.chmod(0o600)


def run(*args, env=None, **kwargs):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, **kwargs)


async def databases(domains=('identity','catalog','service_operations'), retained=None):
    config = json.loads(
        subprocess.check_output(
            ["./infra/foundation/compose.sh", "config", "--format", "json"], cwd=ROOT
        )
    )
    password = config["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
    admin = await asyncpg.connect(
        f"postgresql://postgres:{quote(password)}@127.0.0.1:54329/postgres"
    )
    values = dict(retained or {})
    try:
        for domain in domains:
            if domain in values:
                continue
            name = "bt_l15_" + domain + "_" + uuid4().hex[:24]
            owner, runtime = name + "_owner", name
            passwords = {role: secrets.token_urlsafe(24) for role in (owner, runtime)}
            for role in (owner, runtime):
                await admin.execute(
                    await admin.fetchval(
                        "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',$1::text,$2::text)",
                        role,
                        passwords[role],
                    )
                )
            await admin.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
            setup = await asyncpg.connect(
                f"postgresql://postgres:{quote(password)}@127.0.0.1:54329/{name}"
            )
            try:
                await setup.execute(f'''REVOKE ALL ON DATABASE "{name}" FROM PUBLIC;
                GRANT CONNECT ON DATABASE "{name}" TO "{runtime}";
                REVOKE ALL ON SCHEMA public FROM PUBLIC;
                ALTER SCHEMA public OWNER TO "{owner}";
                GRANT USAGE ON SCHEMA public TO "{runtime}";
                ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}";
                ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}";''')
            finally:
                await setup.close()
            values[domain] = {
                kind: f"postgresql://{role}:{quote(passwords[role])}@host.docker.internal:54329/{name}"
                for kind, role in (("owner", owner), ("runtime", runtime))
            }
            persist(OUT / (PROJECT + "-databases.key"), values)
            persist(OUT / "proof-databases.key", values)
    finally:
        await admin.close()
    return values


async def ready(origin, container=None):
    async with httpx.AsyncClient(timeout=3) as client:
        for attempt in range(90):
            if container and attempt % 5 == 0:
                state = subprocess.check_output(['docker','inspect','--format','{{.State.Status}}',container],text=True).strip()
                if state in ('exited','dead'):
                    raise RuntimeError('Own proof service exited before readiness: '+container)
            try:
                response = await client.get(origin + "/health/ready")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    raise RuntimeError("Own proof service did not become ready: " + origin)


async def call(origin, method, path, body=None, token=None, key=None):
    async with httpx.AsyncClient(base_url=origin, timeout=15) as client:
        response = await client.request(
            method,
            path,
            json=body,
            headers={
                "Origin": ORIGIN,
                "Idempotency-Key": key or uuid4().hex,
                **({"Authorization": "Bearer " + token} if token else {}),
            },
        )
        response.raise_for_status()
        return response.json()


async def prepare(env):
    identity = "http://127.0.0.1:8315"
    catalog = "http://127.0.0.1:8415"
    directory = "http://127.0.0.1:8515"
    actors = {}
    for name in ("operator", "buyer", "brand", "other"):
        record = {
            "email": f"l15-{name}-{uuid4().hex[:10]}@example.test",
            "password": secrets.token_urlsafe(24),
            "display_name": "Sample isolated " + name,
        }
        session = await call(identity, "POST", "/v1/accounts/register", record)
        actors[name] = {**record, "id": session["account"]["id"]}
    persist(OUT / "actors.key", actors)
    run(
        *COMPOSE,
        "exec",
        "-T",
        "--user",
        "root",
        "-e",
        "PYTHONPATH=/app:/opt/domain-contracts",
        "identity",
        "python",
        "/proof/bootstrap_identity.py",
        env=env,
    )
    sessions = {
        name: await call(
            identity,
            "POST",
            "/v1/accounts/login",
            {"email": record["email"], "password": record["password"]},
        )
        for name, record in actors.items()
    }
    operator = sessions["operator"]["access_token"]
    brand = await call(
        identity,
        "POST",
        "/v1/businesses",
        {
            "legal_name": "Sample Isolated Brand SAL",
            "public_name": "Sample Atelier Brand",
            "kind": "brand",
            "capabilities": ["sales", "customization"],
            "assurance_reference": "SAMPLE-L15-ONBOARDING",
            "reason": "Explicit sample business onboarding",
            "sample": True,
        },
        operator,
    )
    await call(
        identity,
        "POST",
        "/v1/memberships",
        {
            "business_id": brand["id"],
            "subject_id": actors["brand"]["id"],
            "capabilities": [
                "business.stock.write",
                "business.jobs.write",
                "business.records.read",
            ],
            "qualifications": ["Sample official customization scope"],
            "intervention_scope": "Sample customization assessment and stock only",
            "reason": "Separate sample operator grants exact brand scope",
        },
        operator,
    )
    sessions["brand"] = await call(
        identity,
        "POST",
        "/v1/accounts/login",
        {"email": actors["brand"]["email"], "password": actors["brand"]["password"]},
    )
    other_brand = await call(
        identity,
        "POST",
        "/v1/businesses",
        {
            "legal_name": "Sample Other Brand SAL",
            "public_name": "Sample Other Brand",
            "kind": "brand",
            "capabilities": ["customization"],
            "assurance_reference": "SAMPLE-L15-OTHER",
            "reason": "Separate sample business boundary",
            "sample": True,
        },
        operator,
    )
    await call(
        identity,
        "POST",
        "/v1/memberships",
        {
            "business_id": other_brand["id"],
            "subject_id": actors["other"]["id"],
            "capabilities": ["business.jobs.write", "business.records.read"],
            "qualifications": ["Sample unrelated brand scope"],
            "intervention_scope": "Unrelated brand only",
            "reason": "Separate sample brand boundary",
        },
        operator,
    )
    staff = sessions["brand"]["access_token"]
    buyer = sessions["buyer"]["access_token"]
    brand_id = brand["id"]
    if 'service-operations' in SERVICES:
        await call(
            directory, 'PUT', f'/v1/directory/businesses/{brand_id}',
            {'expected_revision':0,'capabilities':['customization'],'contact':'sample-atelier@example.test',
             'visit_en':'Sample content; no real appointment','visit_ar':'محتوى تجريبي؛ ليس موعداً فعلياً',
             'scope_en':'Sample brand customization assessment','scope_ar':'تقييم تخصيص لدى علامة تجريبية',
             'published':True}, staff)
    catalogue = json.loads(
        (
            ROOT / "packages/contracts-catalog/options/fixtures/options.v1.json"
        ).read_text()
    )
    for option in catalogue["options"]:
        await call(
            catalog,
            "PUT",
            f"/v1/brand-options/brands/{brand_id}/{option['kind']}/{option['id']}",
            option["definition"],
            staff,
        )
    movement_id = str(uuid4())
    mounting = {
        "case": "sample-case-38",
        "dial": "sample-dial-01",
        "hands": "sample-hands-01",
        "functions": ["hours", "minutes"],
    }
    await call(
        catalog,
        "PUT",
        f"/v1/options/movement/{movement_id}",
        {
            "brand_id": brand_id,
            "expected_revision": 0,
            "label_en": "Sample · Manual movement",
            "label_ar": "نموذج · حركة يدوية",
            "caliber": catalogue["caliber"],
            "cases": [mounting["case"]],
            "dials": [mounting["dial"]],
            "hands": [mounting["hands"]],
            "functions": mounting["functions"],
            "quote_minor": 25000,
            "currency": "USD",
            "active": True,
        },
        staff,
    )
    configuration_id = str(uuid4())
    for revision, kind in enumerate(("color", "material", "dial", "sophistication")):
        option = next(item for item in catalogue["options"] if item["kind"] == kind)
        await call(
            catalog,
            "PUT",
            f"/v1/brand-options/configurations/{configuration_id}/{kind}",
            {
                "brand_id": brand_id,
                "base_model": catalogue["base_model"],
                "caliber": catalogue["caliber"],
                "component": option["definition"]["component"],
                "option_id": option["id"],
                "option_revision": 1,
                "expected_revision": revision,
                "reference_ids": [],
            },
            buyer,
        )
    movement = await call(
        catalog,
        "POST",
        "/v1/options/movement/selections",
        {
            "brand_id": brand_id,
            "option_id": movement_id,
            "expected_revision": 0,
            "option_revision": 1,
            "configuration": mounting,
        },
        buyer,
    )
    facts = {
        "brand": "Sample Atelier Brand",
        "model": "Sample listed watch",
        "reference": "SAMPLE-L15",
        "year": 2020,
        "condition": "Sample content with declared light wear",
        "component_wear": {"case": "Sample light wear"},
        "location": "Beirut",
        "included": [],
        "no_documents": True,
        "modified": False,
        "modifications": [],
        "ownership_confirmed": True,
        "sale_mode": "fixed_price",
        "currency": "USD",
        "price_minor": 500000,
    }
    listing = await call(
        catalog,
        "POST",
        f"/v1/seller/listings?organization_id={brand_id}",
        {"facts": facts, "demo_key": "DEMO-WATCH-01"},
        staff,
    )
    public = {
        "sample": True,
        "project": PROJECT,
        "origin": ORIGIN,
        "brand_id": brand_id,
        "other_brand_id": other_brand["id"],
        "configuration_id": configuration_id,
        "configuration_revision": 4,
        "movement_selection_id": movement["id"],
        "movement_revision": movement["revision"],
        "listing_id": listing["id"],
        "emails": {name: record["email"] for name, record in actors.items()},
        "outcomes_seeded": False,
    }
    persist(OUT / "proof-public.json", public)
    return public


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for port in PORTS:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    for file in ("proof.ready", "proof.stop"):
        (OUT / file).unlink(missing_ok=True)
    resume_existing = '--resume-existing' in sys.argv
    if resume_existing:
        # These credentials address only this proof's retained restricted DBs.
        # No actor, source choice, submission or outcome is reseeded on resume.
        env = {**os.environ, **json.loads((OUT / 'proof-environment.key').read_text())}
        if not json.loads((OUT / 'proof-public.json').read_text()).get('sample'):
            raise RuntimeError('Resume requires this proof\'s labelled sample metadata')
    else:
        values = await databases(tuple(service.replace('-','_') for service in SERVICES))
        signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        env = {
            **os.environ,
            "L15_PUBLIC_KEY": signing.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
            "L15_PRIVATE_KEY": signing.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        }
    if resume_existing:
        values = await databases(tuple(service.replace('-','_') for service in SERVICES),
            retained=json.loads((OUT/'proof-databases.key').read_text()))
    for domain, urls in values.items():
        for kind, url in urls.items():
            env['L15_'+domain.upper()+'_'+kind.upper()] = url
    if LISTING_AUTHORITIES:
        env.setdefault('L15_SIMULATED_PAYMENT_SECRET', secrets.token_urlsafe(32))
        if not env.get('L15_PRICING_IMAGE'):
            available = subprocess.check_output(['docker','image','ls','beirut-time/pricing',
                '--format','{{.Repository}}:{{.Tag}}'],text=True).splitlines()
            image = next((name for name in available if name.endswith(':local')),None)
            image = image or next((name for name in available if ':test-' in name),None)
            if not image:
                raise RuntimeError('An existing Pricing runtime/test image is required; this proof never builds peer images')
            env['L15_PRICING_IMAGE'] = image
    persist(
        OUT / "proof-environment.key",
        {name: value for name, value in env.items() if name.startswith("L15_")},
    )
    web = None
    started = False
    try:
        if '--reuse-image' in sys.argv:
            run('docker','image','inspect','beirut-time/catalog:l15-proof',stdout=subprocess.DEVNULL)
        else:
            run(
                'docker','build','--target','runtime','--build-arg','SERVICE_PATH=services/catalog',
                '-f','services/catalog/runtime/Dockerfile','-t','beirut-time/catalog:l15-proof','.',env=env)

        # The local PostgreSQL endpoint is shared; these owner credentials address
        # only the generated per-domain proof namespaces, never ordinary schemas.
        if not resume_existing:
            persist(OUT / 'actors.key', {})
        for domain in SERVICES:
            run(
                *COMPOSE,
                "run",
                "--no-deps",
                "--name",
                PROJECT + "-" + domain + "-migrate",
                domain + "-migrate",
                env=env,
            )
        started = True
        run(
            *COMPOSE,
            "up",
            "-d",
            "--no-build",
            *SERVICES,
            env=env,
        )
        for service, port in zip(SERVICES, PORTS[1:], strict=True):
            await ready('http://127.0.0.1:'+str(port), PROJECT+'-'+service+'-1')
        if not resume_existing:
            await prepare(env)
        public = json.loads((OUT / 'proof-public.json').read_text())
        public['project'] = PROJECT
        persist(OUT / 'proof-public.json', public)
        web_env = {
            **os.environ,
            "PATH": "/Users/andrew/.harness/homes/430-project/firstmate/data/bt-tools/bin:"
            + os.environ["PATH"],
            "BT_ALLOWED_WEB_ORIGINS": ORIGIN,
            "BT_PUBLIC_WEB_ORIGINS": ORIGIN,
            "NODE_OPTIONS": "--max-old-space-size=1024",
        }
        for service in (
            "identity",
            "catalog",
            "auction",
            "pricing",
            "orders",
            "eligibility",
            "trust",
            "communications",
            "service-operations",
        ):
            web_env[service.upper().replace("-", "_") + "_API_URL"] = (
                "http://127.0.0.1:9"
            )
        web_env.update(
            IDENTITY_API_URL="http://127.0.0.1:8315",
            CATALOG_API_URL="http://127.0.0.1:8415",
            SERVICE_OPERATIONS_API_URL="http://127.0.0.1:8515",
        )
        if LISTING_AUTHORITIES:
            web_env.update(PRICING_API_URL='http://127.0.0.1:8615',ORDERS_API_URL='http://127.0.0.1:8715',
                           AUCTION_API_URL='http://127.0.0.1:8815')
        with (OUT / "proof-web.log").open("w") as log:
            web = subprocess.Popen(
                [
                    "pnpm",
                    "--dir",
                    "web",
                    "exec",
                    "next",
                    "dev",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    "3315",
                ],
                cwd=ROOT,
                env=web_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            async with httpx.AsyncClient(timeout=3) as client:
                for _ in range(60):
                    try:
                        if (
                            await client.get(ORIGIN + "/en/customize")
                        ).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError("Own web process did not become ready")
                await client.get(ORIGIN+'/api/web/v1/identity/v1/businesses',timeout=60)
                await client.get(ORIGIN+'/en/account',timeout=60)
            (OUT / "proof.ready").write_text(
                "Real sample services ready; stop file closes this proof\n"
            )
            print("L15 sample browser proof ready at " + ORIGIN, flush=True)
            if '--visual-check' in sys.argv:
                visual = await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'tests/lanes/L15/visual-proof.py'),cwd=ROOT)
                try:
                    code = await asyncio.wait_for(visual.wait(),timeout=900)
                except TimeoutError:
                    (OUT/'proof.stop').write_text('Visual check deadline elapsed\n')
                    visual.terminate()
                    await visual.wait()
                    raise RuntimeError('Own bounded visual check timed out') from None
                if code:
                    raise RuntimeError('Own visual check failed; see its preceding diagnostics')
            else:
                deadline = time.monotonic() + 1800
                while not (OUT / "proof.stop").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(2)
    finally:
        if web:
            try:
                os.killpg(web.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                web.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(web.pid, signal.SIGKILL)
                web.wait(timeout=5)
        subprocess.run(
            ["chrome-devtools-axi", "stop"],
            env={**os.environ, "CHROME_DEVTOOLS_AXI_SESSION": "bt-s2-l15"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if started:
            run(*COMPOSE, 'stop', *SERVICES, env=env)
        (OUT / "proof.ready").unlink(missing_ok=True)
        print(
            "Own proof services and browser stopped; databases retained for explicit review",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
