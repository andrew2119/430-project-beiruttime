import json
import os
import time
from uuid import UUID, uuid4
import jwt
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from .support_events import retain_support


def valid_total(value, price):
    # Watch buyer surcharge is three percent, rounded half up to one cent.
    return (
        type(price) is int and 0 <= price <= 9_000_000_000_000_000
        and type(value) is int and value == price + (price * 3 + 50) // 100
    )


def reference(value):
    if not isinstance(value, str):
        raise ValueError("Invalid reference")
    parsed = UUID(value)
    if parsed.int == 0:
        raise ValueError("Invalid reference")
    return parsed


class Sources:
    def __init__(self, app):
        self.app = app
        self.clients = {
            name: DependencyClient(
                name,
                os.environ.get(
                    "BT_" + name.upper() + "_URL",
                    os.environ.get(name.upper() + "_URL", "http://" + name + ":8000"),
                ),
                timeout=1.2,
                concurrency=2,
            )
            for name in ("pricing", "orders", "communications")
        }

    async def json(self, name, method, path, **kwargs):
        key = os.environ.get("BT_SERVICE_AUTH_PRIVATE_KEY", "")
        if not key:
            raise PublicError(
                "service_auth_unavailable",
                "A required source is unavailable.",
                status=503,
            )
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "auction",
                "type": "service",
                "iss": self.app.state.settings.auth_issuer,
                "aud": name,
                "iat": now,
                "exp": now + 60,
            },
            key,
            algorithm="RS256",
        )
        response = await self.clients[name].request(
            method,
            path,
            headers={"Authorization": "Bearer " + token, **kwargs.pop("headers", {})},
            **kwargs,
        )
        if isinstance(response, Unavailable) or response.status_code >= 500:
            raise PublicError(
                "source_unavailable", "The original close remains pending.", status=503
            )
        if response.status_code not in (200, 201):
            raise PublicError(
                "source_held", "The original close requires reconciliation.", status=503
            )
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise PublicError(
                "source_unavailable",
                "The source result cannot be verified.",
                status=503,
            ) from None

    async def aclose(self):
        for client in self.clients.values():
            await client.aclose()


async def reconcile(app, source, auction_id):
    lease = uuid4()
    async with unit_of_work(app.state.pool) as tx:
        row = await tx.fetchrow(
            """UPDATE l13_auction_closes SET lease=$2,lease_until=clock_timestamp()+interval '30 seconds',attempts=attempts+1
            WHERE auction_id=$1 AND state='allocation_pending' AND (lease_until IS NULL OR lease_until<=clock_timestamp()) RETURNING *""",
            auction_id,
            lease,
        )
    if not row:
        return
    try:
        key = "close:" + str(auction_id)
        payload = (
            json.loads(row["allocation_payload"]) if row["allocation_payload"] else None
        )
        if payload is None:
            q = json.loads(row["quote_request"])
            if q["currency"] != "USD":
                raise PublicError("legacy_currency_reconciliation_required", "The retained historical outcome needs reconciliation.", status=409)
            quote_key = "winner-quote:" + str(auction_id)
            quoted = await source.json(
                "pricing",
                "POST",
                "/internal/v2/auction-quotes",
                headers={"Idempotency-Key": quote_key},
                json={
                    "auction_id": str(auction_id),
                    "expected_revision": q["expected_revision"],
                    "buyer_id": str(row["winner_id"]),
                    "operation_key": quote_key,
                },
            )
            basis = quoted.get("quote") if quoted.get("status") == "succeeded" else None
            if not isinstance(basis, dict):
                raise PublicError(
                    "quote_held",
                    "The winner quote construction is not confirmed.",
                    status=503,
                )
            watch = await source.json(
                "orders", "GET", f"/internal/v2/watches/{q['watch_id']}"
            )
            if (
                watch.get("watch_id") != q["watch_id"]
                or watch.get("listing_id") != q["listing_id"]
                or watch.get("source_id") != str(auction_id)
                or watch.get("status") != "fenced"
                or watch.get("auction_committed") is not True
                or type(watch.get("listing_revision")) is not int
                or type(watch.get("revision")) is not int
                or watch["listing_revision"] < 1
                or watch["revision"] < 1
            ):
                raise PublicError(
                    "commitment_held",
                    "The winner commitment cannot be verified.",
                    status=503,
                )
            if (
                basis.get("buyer_id") != str(row["winner_id"])
                or basis.get("listing_id") != q["listing_id"]
                or basis.get("price_minor") != row["closing_minor"]
                or basis.get("currency") != q["currency"]
                or basis.get("owner_id") != str(row["winner_id"])
                or basis.get("watch_id") != q["watch_id"]
                or basis.get("listing_revision") != watch["listing_revision"]
                or basis.get("auction_id") != str(auction_id)
                or basis.get("source") != "auction"
                or basis.get("source_verified") is not True
                or basis.get("kind") != "winner"
                or type(basis.get("price_minor")) is not int
                or type(basis.get("listing_revision")) is not int
                or not valid_total(basis.get("payable_minor"), row["closing_minor"])
                or type(basis.get("revision")) is not int
                or basis["revision"] < 1
            ):
                raise PublicError(
                    "quote_held",
                    "The exact winner quote cannot be verified.",
                    status=503,
                )
            payload = {
                "operation_key": key,
                "watch_id": q["watch_id"],
                "listing_id": q["listing_id"],
                "listing_revision": watch["listing_revision"],
                "expected_revision": watch["revision"],
                "source_id": str(auction_id),
                "kind": "winner",
                "buyer_id": str(row["winner_id"]),
                "quote_id": str(reference(basis["id"])),
                "quote_revision": basis["revision"],
                "currency": q["currency"],
                "total_minor": basis["payable_minor"],
            }
            async with unit_of_work(app.state.pool) as tx:
                wrote = await tx.fetchval(
                    """UPDATE l13_auction_closes SET allocation_payload=$3::jsonb
                    WHERE auction_id=$1 AND lease=$2 AND lease_until>clock_timestamp() RETURNING 1""",
                    auction_id,
                    lease,
                    json.dumps(payload),
                )
                if not wrote:
                    return
        result = await source.json(
            "orders",
            "POST",
            "/internal/v2/allocations",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        if result.get("status") not in {"succeeded", "denied"}:
            raise PublicError(
                "allocation_pending",
                "The original allocation remains pending.",
                status=503,
            )
        order = result.get("order", {})
        if not isinstance(order, dict):
            raise ValueError("Invalid allocation result")
        if result["status"] == "succeeded" and (
            order.get("buyer_id") != str(row["winner_id"])
            or order.get("watch_id") != payload["watch_id"]
            or order.get("listing_id") != payload["listing_id"]
            or order.get("quote_id") != payload["quote_id"]
            or order.get("currency") != payload["currency"]
            or type(order.get("total_minor")) is not int
            or order.get("total_minor") != payload["total_minor"]
        ):
            raise PublicError(
                "allocation_pending",
                "The original allocation result cannot be verified.",
                status=503,
            )
        order_id = reference(order["id"]) if result["status"] == "succeeded" else None
        financial_revision = result.get('auction_support_financial_revision') if order_id else None
        if order_id and (type(financial_revision) is not int or financial_revision < 1):
            raise ValueError('The original allocation financial revision is unavailable')
        if result.get("code") is not None and (
            not isinstance(result["code"], str) or len(result["code"]) > 200
        ):
            raise ValueError("Invalid outcome reason")
        async with unit_of_work(app.state.pool) as tx:
            finished = await tx.fetchrow(
                """UPDATE l13_auction_closes SET state=$3,order_id=$4,reason=$5,lease=NULL,lease_until=NULL,
                next_action=CASE WHEN $4::uuid IS NULL THEN 'review_allocation_denial' ELSE NULL END,
                result_revision=result_revision+1,updated_at=clock_timestamp() WHERE auction_id=$1 AND lease=$2 AND lease_until>clock_timestamp() AND state='allocation_pending' RETURNING *""",
                auction_id,
                lease,
                "closed" if order_id else "allocation_denied",
                order_id,
                result.get("code"),
            )
            if finished:
                await retain_support(tx, finished, listing_id=payload['listing_id'], watch_id=payload['watch_id'],
                                     financial_revision=financial_revision)
            if finished and order_id:
                await enqueue(
                    tx,
                    EventEnvelope(
                        type="auction.closed.v1",
                        source="auction",
                        subject=str(auction_id),
                        request_id="close-" + str(auction_id),
                        data={
                            "auction_id": str(auction_id),
                            "listing_id": payload["listing_id"],
                            "winner_id": str(row["winner_id"]),
                            "order_id": str(order_id),
                            "end_version": row["end_version"],
                            "close_version": row["close_version"],
                            "current_minor": row["closing_minor"],
                            "currency": payload["currency"],
                            "outcome": "winner",
                        },
                    ),
                    ["communications-auction-results"],
                )
    except (PublicError, ValueError, KeyError, TypeError):
        # Lost responses never reopen or recalculate a winner. Bound retries and preserve immutable payload.
        async with app.state.pool.acquire() as tx:
            await tx.execute(
                """UPDATE l13_auction_closes SET lease=NULL,lease_until=NULL,
                next_attempt_at=clock_timestamp()+interval '5 seconds',updated_at=clock_timestamp()
                WHERE auction_id=$1 AND lease=$2""",
                auction_id,
                lease,
            )
