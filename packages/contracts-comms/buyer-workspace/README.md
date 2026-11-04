# Buyer workspace v1

`GET /v1/buyer-workspace` on Communications requires a verified, current buyer
session. Owner comes from the live session, never a URL/header/body. Responses
are no-store and omit other buyers, private caps, credentials and evidence.
Auction and Orders use independent bounded clients; malformed/cross-owner or
unavailable sources become unavailable sections, never empty-success or paid.
A revoked source denies the complete composition. Nested deadlines (300ms for
Identity, 600ms for parallel sources) leave room inside the 1.2s gateway budget.

Published implementation handoff: `module.json`, `models.py`, `composition.py`
and `routes.py` belong under `services/communications/modules/buyer-workspace/`.
The optional `implementation/web/` snapshot preserves the owned web paths;
consumers may copy it uncommitted for integration. Contract/index files belong
under `packages/contracts-comms/buyer-workspace/`.

## Sources

- Auction `GET /v1/my-bids?limit=100`: awaiting exact provider DTO. Provisional
  fixture is `{items:[{auction_id,listing_id,buyer_id,status:leading|outbid,
  current_price_minor,currency,revision,ends_at,is_demo}],next_cursor:null|string}`.
  Unknown private fields or another owner's row fail unavailable.
- Orders `GET /v1/me/reservations?limit=100`: published allocation v1 buyer-only
  projection, exactly `{items:[{reservation_id,listing_id,buyer_id,
  state:'awaiting_payment',total_minor,currency,revision,expires_at,is_demo}],
  next_cursor:null|UUID}`. Limit 1–100; owner-scoped UUID keyset cursor. Only
  current buyer's unexpired awaiting-payment records appear. Sample content
  provenance is carried from the real source, never inferred or seeded here.
  Unknown-payment/expired holds stay in Orders, never masquerade as ready.

The output strips buyer_id and adds relative review actions constructed locally.
`/checkout?order=<reservation_id>` links to the owning review workspace (confirm
its resume behavior in connected integration). Payment/delivery remain false.
Unacknowledged/pending requests stay in Checkout, not invented as orders. A
non-null cursor states that more source activity exists, not a complete archive.

IDs are UUIDs; amounts are exact bounded integer minor units; timestamps are
aware. The same bearer and request reference are forwarded. There are no
cross-service SQL/imports, cached successes, projection writes or artificial
migrations: this read module owns no persistent business state. Auction/Orders
transaction outboxes remain the only activity source. Final auction results
remain unavailable in Sprint 1. Fixture tests are not connected-demo acceptance.
