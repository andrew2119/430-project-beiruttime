"""Real Identity guards plus published provider code, never a fake principal.

State changes select a signed-in test actor or mutate a synthetic case fixture.
The production routes and all their acknowledged writes remain real PostgreSQL.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import httpx
import jwt
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover

HERE = Path(__file__).resolve().parent
SOURCE = (
    Path("/app/modules")
    if Path("/app/modules").exists()
    else HERE.parents[2] / "services/identity/modules"
)
MODULES = (
    Path("/tmp/l02-contract-modules")
    if Path("/app/modules").exists()
    else HERE / ".contract-runtime/modules"
)
if MODULES.exists():
    shutil.rmtree(MODULES)
shutil.copytree(SOURCE, MODULES)
for name in ("accounts", "private-seller"):
    if not (SOURCE / name / "module.json").exists():
        shutil.copytree(
            HERE / "fixtures/modules" / name, MODULES / name, dirs_exist_ok=True
        )
try:
    provider = importlib.util.find_spec("service_app.identity")
except ModuleNotFoundError:
    provider = None
if provider is None:
    sys.path.insert(0, str(HERE / "fixtures/runtime"))
os.environ["BT_MODULES_PATH"] = str(MODULES)
pytest_plugins = ["bt_runtime.testing"]
PERMISSIONS = [
    "identity.businesses.manage",
    "identity.membership.manage",
    "identity.private-seller.assign",
    "identity.private-seller.review",
]
PASSWORD = "Sample passphrase 2026!"


class ScenarioClient(httpx.AsyncClient):
    async def request(self, method, url, **kwargs):
        body = kwargs.get("json")
        if (
            str(url) == "/v1/contacts/challenges"
            and isinstance(body, dict)
            and body.get("reauthentication") == "recent-proof"
        ):
            body = dict(body)
            recipient = body["recipient"].strip()
            recipient = (
                "".join(
                    str(int(char)) if char.isdecimal() else char for char in recipient
                )
                if body["channel"] == "phone"
                else recipient.lower()
            )
            proof = await self.post(
                "/v1/accounts/reauthenticate",
                json={
                    "password": PASSWORD,
                    "purpose": "contact-change",
                    "binding": body["channel"] + ":" + recipient,
                },
            )
            if proof.status_code != 200:
                return proof
            body.pop("reauthentication")
            body["proof"] = proof.json()["proof"]
            kwargs["json"] = body
        return await super().request(method, url, **kwargs)


@pytest_asyncio.fixture
async def api(database_url, monkeypatch):
    monkeypatch.setenv("BT_CONTACT_SIMULATOR", "1")
    monkeypatch.setenv("BT_WEB_ORIGIN", "http://identity")
    monkeypatch.setenv("BT_LOCAL_HTTP", "1")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        private.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    monkeypatch.setenv("BT_AUTH_PRIVATE_KEY", private_pem)
    operator, applicant, reviewer, outsider = uuid4(), uuid4(), uuid4(), uuid4()
    state = {
        "actor": operator,
        "permissions": PERMISSIONS.copy(),
        "applicant": applicant,
        "reviewer": reviewer,
        "outsider": outsider,
        "revision": 1,
        "complete": True,
        "seller_type": "private",
        "sessions": {},
        "last_actor": None,
        "case_state": None,
        "authority": {
            subject: tuple(PERMISSIONS)
            for subject in (operator, applicant, reviewer, outsider)
        },
    }
    app = create_app(
        Settings(
            database_url=database_url,
            modules_path=MODULES,
            service_name="identity",
            auth_public_key=public,
        )
    )
    pool = await db.create_pool(database_url)
    app.state.pool = pool
    accounts = next(
        module for module in discover(MODULES) if module.id == "L01.accounts"
    )
    encoded = accounts.load("security.py:hash_password")(PASSWORD)
    async with pool.acquire() as tx:
        for subject in (operator, applicant, reviewer, outsider):
            await tx.execute(
                "INSERT INTO identity_accounts(id,email,display_name,password_hash) VALUES($1,$2,$3,$4)",
                subject,
                str(subject) + "@example.test",
                "Sample individual",
                encoded,
            )
            sid = uuid4()
            await tx.execute(
                "INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,now()+interval '1 hour')",
                sid,
                subject,
            )
            state["sessions"][subject] = sid
            await tx.execute(
                "INSERT INTO identity_access_grants(id,subject_id,role,permissions) VALUES($1,$2,'operator',$3)",
                uuid4(),
                subject,
                PERMISSIONS,
            )

    async def prepare(request):
        async with pool.acquire() as tx:
            # Explicitly switching test actors models a fresh sign-in. Holding the
            # same actor preserves revoked lineages for fence/race assertions.
            actor = state["actor"]
            if state["last_actor"] != actor:
                active = await tx.fetchval(
                    "SELECT id FROM identity_sessions WHERE id=$1 AND revoked_at IS NULL",
                    state["sessions"][actor],
                )
                if not active and not state.get("keep_session"):
                    sid = uuid4()
                    await tx.execute(
                        "INSERT INTO identity_sessions(id,subject_id,expires_at) VALUES($1,$2,now()+interval '1 hour')",
                        sid,
                        actor,
                    )
                    state["sessions"][actor] = sid
                state["last_actor"] = actor
            if state["authority"][actor] != tuple(state["permissions"]):
                await tx.execute(
                    "UPDATE identity_access_grants SET permissions=$2 WHERE subject_id=$1 AND organization_id IS NULL AND role='operator'",
                    actor,
                    state["permissions"],
                )
                state["authority"][actor] = tuple(state["permissions"])
            if request.method == "POST" and request.url.path == "/v1/private-reviews":
                body = json.loads(request.content)
                if state["seller_type"] == "private":
                    identity = UUID(body["application_id"])
                    await tx.execute(
                        """INSERT INTO identity_private_applications(id,subject_id,revision,status,identity_name,contact,payout_reference)
                        VALUES($1,$2,$3,'pending','Sample individual','Sample private contact','DEMO-PAYOUT') ON CONFLICT DO NOTHING""",
                        identity,
                        applicant,
                        state["revision"],
                    )
                    for kind in ("identity", "possession"):
                        content = b"Sample evidence, not a real identity document"
                        if not await tx.fetchval(
                            "SELECT id FROM identity_private_evidence WHERE application_id=$1 AND kind=$2",
                            identity,
                            kind,
                        ):
                            await tx.execute(
                                """INSERT INTO identity_private_evidence(id,application_id,subject_id,kind,content,sha256)
                                VALUES($1,$2,$3,$4,$5,$6)""",
                                uuid4(),
                                identity,
                                applicant,
                                kind,
                                content,
                                hashlib.sha256(content).hexdigest(),
                            )
                    state["case_state"] = (state["revision"], state["complete"])
            if state["case_state"] and state["case_state"] != (
                state["revision"],
                state["complete"],
            ):
                await tx.execute(
                    "UPDATE identity_private_applications SET revision=$2 WHERE subject_id=$1",
                    applicant,
                    state["revision"],
                )
                if not state["complete"]:
                    await tx.execute(
                        "DELETE FROM identity_private_evidence WHERE subject_id=$1 AND kind='identity'",
                        applicant,
                    )
                else:
                    application_id = await tx.fetchval(
                        "SELECT id FROM identity_private_applications WHERE subject_id=$1",
                        applicant,
                    )
                    content = b"Sample restored identity evidence"
                    await tx.execute(
                        """INSERT INTO identity_private_evidence(id,application_id,subject_id,kind,content,sha256)
                        VALUES($1,$2,$3,'identity',$4,$5)""",
                        uuid4(),
                        application_id,
                        applicant,
                        content,
                        hashlib.sha256(content).hexdigest(),
                    )
                state["case_state"] = (state["revision"], state["complete"])
        if "authorization" not in request.headers:
            now = datetime.now(timezone.utc)
            request.headers["authorization"] = "Bearer " + jwt.encode(
                {
                    "sub": str(state["actor"]),
                    "sid": str(state["sessions"][state["actor"]]),
                    "iss": "beirut-time-identity",
                    "aud": "beirut-time",
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                    "type": "access",
                },
                private,
                algorithm="RS256",
            )
        request.headers.setdefault("origin", "http://identity")

    async with ScenarioClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://identity",
        event_hooks={"request": [prepare]},
    ) as client:
        yield client, state, pool, app
    await pool.close()
