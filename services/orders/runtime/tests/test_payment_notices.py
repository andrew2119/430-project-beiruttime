from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from bt_runtime.app import db
from bt_runtime.app.settings import Settings
from service_app.bootstrap import create_app
from service_app.payment_notices import ensure_payment_notice


@pytest.mark.asyncio
async def test_verified_callback_starts_the_payment_clock(database_access):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(
        service_name="orders",
        database_url=database_access.runtime_url,
        service_auth_public_key=key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode(),
    )
    app = create_app(settings)
    app.state.pool = await db.create_pool(settings.database_url)
    watch, listing, buyer, seller, order, quote, notice = (uuid4() for _ in range(7))
    try:
        async with db.unit_of_work(app.state.pool) as tx:
            await tx.execute(
                """INSERT INTO l08_watches(id,listing_id,seller_id,listing_revision,sale_mode)
                VALUES($1,$2,$3,1,'fixed')""", watch, listing, seller,
            )
            reserved = await tx.fetchrow(
                """INSERT INTO l08_orders(id,watch_id,listing_id,buyer_id,seller_id,quote_id,currency,total_minor,state)
                VALUES($1,$2,$3,$4,$5,$6,'USD',125000,'awaiting_notification') RETURNING *""",
                order, watch, listing, buyer, seller, quote,
            )
            await ensure_payment_notice(tx, reserved, "payment-test")
            event = await tx.fetchval("SELECT event_id FROM l13_payment_notices WHERE order_id=$1", order)
        notified_at = datetime.now(timezone.utc)
        token = jwt.encode({
            "sub": "communications", "type": "service", "iss": settings.auth_issuer,
            "aud": "orders", "iat": notified_at, "exp": notified_at + timedelta(minutes=1),
        }, key, algorithm="RS256")
        payload = {
            "event_id": str(event), "notice_id": str(notice), "order_id": str(order), "buyer_id": str(buyer),
            "notified_at": notified_at.isoformat(), "verified_delivery_recorded": True,
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": "Bearer " + token}
            response = await client.post("/internal/v3/payment-notices", json=payload, headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "succeeded"
            assert result["order"]["state"] == "awaiting_payment"
            assert datetime.fromisoformat(result["order"]["notified_at"]) == notified_at
            assert datetime.fromisoformat(result["order"]["deadline"]) == notified_at + timedelta(hours=48)
            replay = await client.post("/internal/v3/payment-notices", json=payload, headers=headers)
            assert replay.json() == result
        async with db.unit_of_work(app.state.pool) as tx:
            state = await tx.fetchrow("SELECT state,notified_at FROM l08_orders WHERE id=$1", order)
            assert tuple(state) == ("awaiting_payment", notified_at)
    finally:
        await app.state.pool.close()
