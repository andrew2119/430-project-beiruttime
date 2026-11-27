"""Connected Auction/Orders/Pricing close proof. No SQL winners or seeded orders."""

from datetime import datetime, timedelta, timezone
import json
import time


def run(
    call,
    seller,
    buyer,
    buyer_id,
    listing_id,
    suffix,
    pricing_token,
    *,
    expect_pending=False,
):
    now = datetime.now(timezone.utc)
    created = call(
        "auction",
        "POST",
        "/v1/auctions",
        {
            "listing_id": listing_id,
            "currency": "USD",
            "opening_minor": 500000,
            "increment_bands": [{"from_minor": 0, "step_minor": 1000}],
            "reserve_minor": None,
            "starts_at": (now - timedelta(seconds=1)).isoformat(),
            "ends_at": (now + timedelta(seconds=20)).isoformat(),
        },
        seller,
        headers={"Idempotency-Key": "real-auction-" + suffix},
    )
    auction_id = created["auction_id"]
    lot = created["auction"]
    quote_body = {
        "subject_id": auction_id,
        "subject_revision": lot["revision"],
        "purpose": "bid",
        "source": "sample",
        "currency": "USD",
        "price_minor": 500000,
        "schedule_id": "sample-v1",
    }
    q = call(
        "pricing",
        "POST",
        "/v1/quotes",
        quote_body,
        buyer,
        headers={"Idempotency-Key": "real-bid-quote-" + suffix},
    )
    call(
        "pricing",
        "POST",
        "/v1/quotes/" + q["id"] + "/review",
        {
            **quote_body,
            "quote_revision": q["revision"],
            "payable_minor": q["payable_minor"],
        },
        buyer,
        headers={"Idempotency-Key": "real-bid-review-" + suffix},
    )
    command = {
        "amount_minor": 500000,
        "fee_quote_id": q["id"],
        "expected_revision": lot["revision"],
    }
    bid = call(
        "auction",
        "POST",
        "/v1/auctions/" + auction_id + "/bids",
        command,
        buyer,
        headers={"Idempotency-Key": "real-bid-" + suffix},
    )
    if bid.get("status") != "succeeded" or bid.get("code") != "bid_accepted":
        raise RuntimeError("Actual first-bid operation did not succeed")
    result_path = "/v1/auctions/" + auction_id + "/result"
    decided = None
    for _ in range(180):
        decided = call("auction", "GET", result_path)
        if decided["status"] != "not_closed":
            break
        time.sleep(0.2)
    if not decided or decided["status"] == "not_closed":
        raise RuntimeError(
            "Canonical deadline worker did not close the real accepted bid"
        )
    for _ in range(50):
        decided = call("auction", "GET", result_path)
        if decided["status"] == "closed":
            break
        time.sleep(0.2)
    closed_lot = call("auction", "GET", "/v2/auctions/" + auction_id)
    quote_key = "winner-quote:" + auction_id
    winner_quote = call(
        "pricing",
        "POST",
        "/internal/v2/auction-quotes",
        {
            "auction_id": auction_id,
            "expected_revision": closed_lot["revision"],
            "buyer_id": buyer_id,
            "operation_key": quote_key,
        },
        pricing_token,
        headers={"Idempotency-Key": quote_key},
    )
    exact = winner_quote.get("quote", {})
    if (
        winner_quote.get("status") != "succeeded"
        or exact.get("owner_id") != buyer_id
        or exact.get("auction_id") != auction_id
        or exact.get("price_minor") != 500000
        or exact.get("payable_minor") != 515000
        or exact.get("kind") != "winner"
        or exact.get("source_verified") is not True
    ):
        raise RuntimeError("Actual canonical winner quote construction failed")
    mine = call(
        "auction", "GET", "/v1/auctions/" + auction_id + "/my-result", token=buyer
    )
    if (
        not mine["won"]
        or decided["closing_minor"] != 500000
        or decided["currency"] != "USD"
    ):
        raise RuntimeError("Canonical actual winner/current price mismatch")
    if expect_pending:
        if decided["status"] != "allocation_pending" or mine["order_id"] is not None:
            raise RuntimeError(
                "Unavailable retained Pricing source did not preserve the pending close"
            )
        evidence = {
            "connected_decision": True,
            "allocation": "pending",
            "paid": False,
            "auctionId": auction_id,
            "listingId": listing_id,
        }
    else:
        if decided["status"] != "closed" or not mine["order_id"]:
            raise RuntimeError(
                "Real close did not produce the winner's awaiting-payment order"
            )
        checkout = call(
            "orders", "GET", "/v1/orders/" + mine["order_id"] + "/checkout", token=buyer
        )
        if (
            checkout["order"]["state"] != "awaiting_payment"
            or checkout["quote"]["payable_minor"] != 515000
        ):
            raise RuntimeError(
                "Winner order did not retain exact actual Pricing economics"
            )
        # Replaying the original bid cannot reopen or manufacture another order.
        replay = call(
            "auction",
            "POST",
            "/v1/auctions/" + auction_id + "/bids",
            command,
            buyer,
            headers={"Idempotency-Key": "real-bid-" + suffix},
        )
        after = call(
            "auction", "GET", "/v1/auctions/" + auction_id + "/my-result", token=buyer
        )
        if replay != bid or after["order_id"] != mine["order_id"]:
            raise RuntimeError("Close replay changed the canonical winner/order")
        evidence = {
            "connected_decision": True,
            "allocation": "succeeded",
            "paid": False,
            "auctionId": auction_id,
            "orderId": mine["order_id"],
            "listingId": listing_id,
        }
    print("Auction evidence: " + json.dumps(evidence), flush=True)
    return evidence
