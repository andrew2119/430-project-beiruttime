# Own bids read v1 — exact L06 handoff

`GET /v1/my-bids?limit=100&cursor=<UUID>` requires a fresh Identity principal. Owner is inferred only from its subject. No caller buyer_id, account header or organization membership can read another buyer's participation. Missing/revoked Identity is denied/unavailable, not empty success.

The accompanying my-bids.v1.json is an exact synthetic wire example, not a seeded marketplace bid or winning result. TypeScript is standalone in my-bids.ts (`AuctionMyBidV1`, `AuctionMyBidsV1`); the core root also exports compatibility aliases `MyBidSummary` and `MyBidPage`.

Important mapping distinctions from the provisional workspace fixture:

- `auction_id` and `id` identify the same Auction; listing_id is the canonical listing reference.
- buyer_id is always the current subject; it is returned only in this owner-private read.
- `status` is the Auction status live|scheduled|ended. **Use my_status for leading|outbid.** Neither field fabricates won/lost, paid, sold or released.
- current_price_minor and current_minor are the same canonical public price; they are finite integer minor units, not a private ceiling.
- next_action is review_bid while not ended, auction_ended afterward. Closing/payment remain unavailable in Sprint 1.
- No `is_demo` marker is invented by this source. Listing provenance belongs to Catalog; do not default missing provenance to a claim that a watch is real/not-demo.
- reserve_set is only a boolean. Reserve amounts, private maxima, session identifiers, fee quote IDs and other buyers' subject IDs never appear.
- leader is an Auction-local masked reference (or null), not a subject UUID.

`limit` is 1–100. Results are ordered by ends_at descending, then Auction UUID descending. The opaque next_cursor is the final returned Auction UUID when more owner records exist; pass it back as cursor. Null means no further rows at that read. A foreign cursor cannot expand owner scope. No rows means no acknowledged participation, not a fabricated awaiting-payment reservation or an empty-success fallback after an outage.

The provider BFF route is `/api/{web|mobile}/v1/auction/v1/my-bids`. Communications consumes the direct `/v1/my-bids` path with the same buyer Bearer token and request reference through its own bounded Auction client. Use the canonical snapshot revision and server time for reconciliation.

Shared handoff path mappings: index.ts → packages/contracts-auction/core/my-bids.ts; my-bids.v1.json → packages/contracts-auction/core/fixtures/my-bids.v1.json; README.md → packages/contracts-auction/core/MY_BIDS.md. These are provider-owned copies for uncommitted integration; take main when the owning branch merges.
