"""Opt-in real owning-runtime Compose proof, reusing the existing proof image."""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse, urlunparse
from uuid import uuid4
import httpx
import jwt
import pytest
from conftest import PASSWORD


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("BT_L02_COMPOSE_PROOF") != "1",
    reason="Opt-in owning-runtime Compose proof",
)
async def test_owning_identity_runtime_compose(api, database_url):
    _, state, _, app = api
    root = Path(__file__).resolve().parents[3]
    parsed = urlparse(database_url)
    runtime = urlunparse(
        parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[0] + "@postgres:5432")
    )
    env = {
        **os.environ,
        "BT_L02_PROOF_DATABASE_URL": runtime,
        "BT_AUTH_PUBLIC_KEY": app.state.settings.auth_public_key,
    }
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "-p",
        "bt-l02-runtime-proof",
        "-f",
        str(root / "tests/lanes/L02/compose.runtime-proof.yaml"),
    ]
    now = datetime.now(timezone.utc)
    operator = jwt.encode(
        {
            "sub": str(state["actor"]),
            "sid": str(state["sessions"][state["actor"]]),
            "iss": "beirut-time-identity",
            "aud": "beirut-time",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "type": "access",
        },
        os.environ["BT_AUTH_PRIVATE_KEY"],
        algorithm="RS256",
    )

    def run(*args):
        subprocess.run(
            [*compose, *args],
            env=env,
            check=True,
            timeout=60,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    try:
        run(
            "up", "-d", "--no-build", "--wait", "--wait-timeout", "30", "identity-proof"
        )
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8202",
            timeout=4,
            headers={"Origin": "http://identity"},
        ) as client:

            async def command(path, body, token=None, method="POST", expected=200):
                headers = {"Idempotency-Key": str(uuid4())}
                if token:
                    headers["Authorization"] = "Bearer " + token
                response = await client.request(
                    method, path, json=body, headers=headers
                )
                assert response.status_code == expected, (path, response.status_code)
                return response.json()

            async def read(path, token=None, expected=200):
                response = await client.get(
                    path, headers={"Authorization": "Bearer " + token} if token else {}
                )
                assert response.status_code == expected, (path, response.status_code)
                return response.json()

            async def register(label):
                email = "sample-" + label + "-" + uuid4().hex + "@example.test"
                result = await command(
                    "/v1/accounts/register",
                    {
                        "email": email,
                        "password": PASSWORD,
                        "display_name": "Sample " + label,
                    },
                    expected=201,
                )
                assert result["principal"]["roles"] == ["buyer"]
                return email, result

            businesses = []
            for kind in ("dealer", "brand"):
                record = await command(
                    "/v1/businesses",
                    {
                        "legal_name": "Sample Compose " + kind + " SAL",
                        "public_name": "Sample Compose " + kind,
                        "kind": kind,
                        "capabilities": ["sales", "servicing"],
                        "assurance_reference": "SAMPLE-COMMUNICATION-" + kind,
                        "reason": "Sample platform communication approved",
                        "sample": True,
                    },
                    operator,
                )
                assert record["authenticated_business"] and record["sample"]
                businesses.append(record)
            email, colleague = await register("colleague")
            grant = await command(
                "/v1/memberships",
                {
                    "business_id": businesses[1]["id"],
                    "subject_id": colleague["account"]["id"],
                    "capabilities": [
                        "business.stock.write",
                        "business.records.read",
                        "business.staff.manage",
                    ],
                    "qualifications": ["Sample stock qualification"],
                    "intervention_scope": "Own sample business only",
                    "reason": "Sample colleague explicitly authorized",
                },
                operator,
            )
            await read(
                "/internal/v1/principal", colleague["access_token"], expected=401
            )
            colleague = await command(
                "/v1/accounts/login", {"email": email, "password": PASSWORD}
            )
            token = colleague["access_token"]
            assert colleague["principal"]["permissions"] == []
            assert (
                "identity.listings.publish"
                in colleague["principal"]["organization_grants"][0]["permissions"]
            )
            await read(f"/v1/businesses/{businesses[1]['id']}/memberships", token)
            await read(
                f"/v1/businesses/{businesses[0]['id']}/memberships", token, expected=403
            )
            proof = await command(
                "/v1/accounts/reauthenticate",
                {
                    "password": PASSWORD,
                    "purpose": "contact-change",
                    "binding": "phone:+96171123456",
                },
                token,
            )
            challenge = await command(
                "/v1/contacts/challenges",
                {
                    "channel": "phone",
                    "recipient": "+٩٦١٧١١٢٣٤٥٦",
                    "revision": 0,
                    "proof": proof["proof"],
                },
                token,
            )
            code = (
                await read(
                    "/v1/contacts/challenges/" + challenge["id"] + "/sample-code", token
                )
            )["code"]
            contact = await command(
                "/v1/contacts/challenges/" + challenge["id"] + "/verify",
                {"code": code},
                token,
            )
            assert contact["phone_verified"] and contact["phone_sample"]
            seller_email, seller = await register("private-owner")
            application = (
                await command(
                    "/v1/private-seller/applications",
                    {
                        "identity_name": "Sample private owner",
                        "contact": seller_email,
                        "payout_reference": "DEMO-COMPOSE-OWNER",
                        "identity_evidence": "DEMO: synthetic identity reference for a labeled sample",
                        "possession_evidence": "DEMO: synthetic possession reference, not a watch inspection",
                        "expected_revision": 0,
                    },
                    seller["access_token"],
                )
            )["application"]
            assigned = await command(
                "/v1/private-reviews",
                {
                    "application_id": application["id"],
                    "reviewer_id": str(state["actor"]),
                    "reason": "Independent sample reviewer assigned",
                },
                operator,
            )
            files = (
                await read(
                    "/v1/private-reviews/" + assigned["id"] + "/evidence", operator
                )
            )["items"]
            assert len(files) == 2
            await read(
                "/v1/private-reviews/" + assigned["id"] + "/evidence",
                token,
                expected=403,
            )
            verdict = {
                "revision": 1,
                "application_revision": 1,
                "state": "approved",
                "reason": "Sample identity and possession references reviewed",
            }
            await command(
                "/v1/private-reviews/" + assigned["id"] + "/verdict", verdict, operator
            )
            principal = await read("/internal/v1/principal", seller["access_token"])
            assert set(principal["roles"]) == {"buyer", "private_seller"}
            assert principal["organization_grants"] == []
            # Restart the real owning process, preserving its real database.
            run("restart", "identity-proof")
            for _ in range(50):
                try:
                    response = await client.get("/health/ready")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Owning runtime did not become ready after restart")
            assert (await read("/v1/contacts", token))["phone_sample"] is True
            assert (
                await read("/v1/private-seller/applications/me", seller["access_token"])
            )["application"]["status"] == "approved"
            await command(
                "/v1/memberships/" + grant["id"],
                {
                    "revision": 1,
                    "state": "suspended",
                    "reason": "Sample staff access explicitly suspended",
                },
                operator,
                method="PATCH",
            )
            await read("/internal/v1/principal", token, expected=401)
            await command(
                "/v1/private-reviews/" + assigned["id"] + "/verdict",
                {
                    **verdict,
                    "revision": 2,
                    "application_revision": 2,
                    "state": "suspended",
                    "reason": "Sample possession assurance withdrawn",
                },
                operator,
            )
            await read("/internal/v1/principal", seller["access_token"], expected=401)
            seller = await command(
                "/v1/accounts/login", {"email": seller_email, "password": PASSWORD}
            )
            history = await read(
                "/v1/private-reviews/" + assigned["id"], seller["access_token"]
            )
            assert len(history["history"]) == 3
            assert history["business_privileges"] is False
            assert history["physical_watch_authentication"] is False
    finally:
        # Keep this task's stopped container for cleanup; never remove shared state.
        run("stop", "--timeout", "5", "identity-proof")
