# Auction events / Communications handoff v1

## Delivery and receiver ownership

The durable notice source is **`auction.bid-accepted.v1`** from `auction`. Manual and maximum admission enqueue it atomically with the bid and operation acknowledgement. Communications derives the outbid notice from the accepted bid. The newer immediately beaten bidder event reconciles that same occurrence.

Outbox destination registry key: `communications`. Runtime URL: `COMMUNICATIONS_URL`, default `http://communications:8000`. The foundation `OutboxRelay` sends `POST /internal/v1/events` with the contracts-core V1 envelope and authenticated short-lived RS256 service token: `sub=auction`, `type=service`, `aud=communications`, `iss=beirut-time-identity` (configured issuer), required exp/iat. User tokens cannot publish.

**L05 owns the opt-in receiver `/internal/v1/events` in `services/communications/modules/bid-notices`.** Do not register that same path in Inbox. The receiver commits the inbox receipt and local notice records in one Communications transaction, then a leased durable worker bridges each record to the L07 Inbox writer. Duplicate envelope IDs are acknowledged with HTTP 200 and `accepted:false`; failed handlers roll back receipt and notices.

## Exact payload

The accompanying `bid-accepted.v1.json` is a synthetic contract example, not database seed data. The data schema is exported as `BidAcceptedEventData` in `packages/contracts-auction/core/models.py` and `index.ts`:

- auction_id / listing_id: UUID strings.
- sequence / revision: positive authoritative integers.
- current_minor: positive integer <= 9,000,000,000,000,000, canonical public price only.
- currency: USD or LBP; monetary minor units have two decimal places.
- ends_at: timezone-aware UTC instant.
- bidder_id: submitting buyer's subject UUID (even if a prior private maximum keeps the lead).
- previous_leader_id: prior leader UUID or null.
- leader_id: resulting leader UUID.

Unknown data fields are rejected, including any private maximum/ceiling. Recipient IDs are service-private and must never be copied into public history or other users' notices.

## Required notices and stable deduplication

- `bid_accepted` to bidder_id for every accepted logical operation.
- `outbid` to previous_leader_id **only** when it is non-null and differs from leader_id. An unchanged leader generates no outbid notice.
- Stable notice ID: UUIDv5(URL namespace, `bid-notice:{envelope.id}:{recipient_id}:{kind}`). Unique key additionally enforces `(event_id,recipient_id,kind)`.
- Required Inbox notices ignore optional email/push settings.
- No winner, paid, sold or closing notice is emitted in Sprint 1.

## L07 Inbox bridge interface

L05 requests `POST /internal/v1/notices` in Communications with a service-purpose token `sub=communications`, `aud=communications`. Idempotent by body id and Idempotency-Key. The payload is:

```json
{
  "id":"<stable-notice-uuid>",
  "recipient_id":"<subject-uuid>",
  "kind":"outbid",
  "resource_type":"auction",
  "resource_id":"<auction-uuid>",
  "href":"/watches/<listing-uuid>",
  "created_at":"<event UTC instant>",
  "data":{"current_minor":410000,"currency":"USD","ends_at":"<UTC instant>","sequence":2}
}
```

The bridge supports both `outbid` and `bid_accepted`. L05 marks delivered only after 2xx; unavailable/error responses remain durable with bounded exponential retry and fenced leases. If Inbox uses a different frozen write contract, publish it and L05 will adapt its worker rather than editing Inbox.

Opening an old notice must fetch current Auction `GET /v1/auctions/{auction_id}`. The historical price, version and end never authorize a new bid; a new fee quote and current revision are required.

## Other Auction events

`auction.opened.v1` and `auction.rules-updated.v1` are sent only to destination `catalog`; data is the public canonical AuctionSnapshot. They are not buyer notices. There is no automatic closing/winner payment in this delivery.

Auction receives `catalog.listing.published.v1` at `POST /internal/v1/events`, with
service subject `catalog`, audience `auction`, and envelope subject equal to
`listing_id`. The publication revision invalidates older Catalog reads for
admission. The receiver and final bid and rules checks take the same listing
lock, including before the first publication is recorded. Rules, scheduling,
payment and allocation still require their canonical command paths.

The same endpoint independently admits Identity's `identity.business-status-changed.v1`,
`identity.membership-changed.v1` and `identity.contact-verified.v1` from service
subject `identity`. Current access and verification are read on each command.

The `auction-timing-v2` destination uses audience `auction` and accepts
`auction.timing-updated.v2`, `auction.listing-revised.v2` and
`auction.listing-edit-aborted.v3` from service subject `auction`. The receiver
reconciles the canonical lot or edit record. Event values never set the schedule
or admit bids. The `catalog` destination uses audience `catalog` and the scoped
`POST /internal/v1/auction/events` receiver for the two public snapshots above.
