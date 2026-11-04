from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from test_identity_modules import key


@pytest.mark.asyncio
async def test_only_authenticated_communications_reads_verified_recipients(api):
    client, state, _, app = api
    subject = state["actor"]
    path = f"/internal/v1/contacts/{subject}/delivery"
    assert (await client.get(path)).status_code == 503
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    app.state.settings.service_auth_public_key = public
    now = datetime.now(timezone.utc)

    def token(subject="communications", kind="service", audience="identity"):
        return jwt.encode(
            {
                "sub": subject,
                "type": kind,
                "iss": "beirut-time-identity",
                "aud": audience,
                "iat": now,
                "exp": now + timedelta(minutes=2),
            },
            private,
            algorithm="RS256",
        )

    for auth, status in [
        ("invalid", 401),
        (token(kind="access"), 403),
        (token("catalog"), 403),
        (token(audience="catalog"), 401),
    ]:
        assert (
            await client.get(path, headers={"Authorization": "Bearer " + auth})
        ).status_code == status
    headers = {"Authorization": "Bearer " + token()}
    assert (await client.get(path, headers=headers)).json()["email"] is None
    response = await client.post(
        "/v1/contacts/challenges",
        json={
            "channel": "email",
            "recipient": "sample@example.test",
            "revision": 0,
            "reauthentication": "recent-proof",
        },
        headers=key(),
    )
    identity = response.json()["id"]
    assert (await client.get(path, headers=headers)).json()["email"] is None
    code = (await client.get(f"/v1/contacts/challenges/{identity}/sample-code")).json()[
        "code"
    ]
    assert (
        await client.post(
            f"/v1/contacts/challenges/{identity}/verify", json={"code": code}
        )
    ).status_code == 200
    assert (await client.get(path, headers=headers)).json()[
        "email"
    ] == "sample@example.test"
    assert (
        await client.get(f"/internal/v1/contacts/{uuid4()}/delivery", headers=headers)
    ).json()["email"] is None
