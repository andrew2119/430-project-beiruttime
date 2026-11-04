# Public Discovery v1

Public reads only. No route here bids, reserves, verifies, publishes or saves a search. There are no business-command writes or new business events: owning command modules retain their transactional outboxes. Discovery owns only its search dictionary migrations and read composition.

## HTTP

- `GET /v1/discovery/watches`: conjunctive `q`, `brand`, `model`/reference, `location`, `min_minor`, `max_minor`, `currency`, `sale_mode` (`fixed`, `auction`, `offer`), `sort`, `cursor`, and `limit` (1–24; default 12). Eastern Arabic/Persian digits and Arabic aliases are accepted. Invalid ranges return `invalid_range` (422). Only visible published listings with confirmed current sale availability appear. An unopened auction is not an active sale result.
- `GET /v1/discovery/watches/{id}`: closed public detail or indistinguishable 404 for private, draft, hidden and withdrawn references. Unknown current stock disables sale actions without inventing a reservation, sale or payment. Optional media/assurance failures remain explicit.
- `GET /v1/discovery/watches/{id}/auction`: rechecks Catalog visibility, then reads canonical Auction core v1 snapshot/history. Available/not_started/unavailable never acknowledges a bid.
- `GET /v1/listings/{id}`: the frozen `CatalogPublicListingV1` publication/fact projection for sibling-service consumers. It is **not** current Orders availability or an independent inspection pass. Command services still validate their current actor, organization and fence authority.

`index.ts` and module-local Pydantic models describe the web read DTOs. Money uses exact decimal-string amounts; filters use integer minor units. USD cents and LBP piastres both have 100 minor units per major unit. Catalog currently publishes USD facts; Auction core also supports LBP. An unstated offer/listing price stays null, never zero.

## Canonical Catalog source and current availability

The module reads only L03's frozen **`catalog_public_listings_v1`** view, within Catalog. It excludes `status != published` and moderation-hidden records. `source_contract.py` validates its public facts, ordered gallery, seller/org references, physical watch and immutable registration identity/mode bindings. It never selects the private base table, possession/serial evidence, fee snapshots, contact details or command receipts.

The Catalog fact revision, registration proof revision and current Orders fence revision are distinct authorities. Publication registration is never treated as current availability. Current `GET /v1/listings/{listing_id}/availability` from Orders must bind physical watch, listing, sale mode and sample provenance. Reserved/fixed-fenced stock is not advertised as available. Unknown/malformed/unavailable stock fails closed; a detail page can remain readable with sale availability unconfirmed. Nothing is inferred to be paid, sold or released.

Official-business assurance comes from current public Identity business status with matching org/kind and active platform-onboarded/authenticated flags. Revoked/unavailable assurance cannot become an independent watch inspection. Private watches explicitly show independent inspection pending; no pass is fabricated. Missing seller-history counts remain unavailable.

Public gallery URLs use `/v1/listings/{listing_id}/photos/{asset_id}/{thumb|card|detail}` through the registered same-origin gateway. Asset references must belong to the visible source gallery. The public photo-credit read supplies source/author/license/change text and EN/AR alternatives. Unavailable attribution suppresses that gallery rather than displaying unattributed external media. No private file URL can enter a Photo DTO.

## Actual Auction timing and stable cursors

Ending-soon comes from Auction's versioned `GET /v1/auction-timing?status=active&limit=100&cursor=...`, ordered by `(current_ends_at,auction_id)` in the owning service. Catalog rechecks every returned reference against its own current visibility and all requested filters, then confirms Orders stock. Default sorts batch-read timing for known auction candidates with `listing_ids=...&status=all`; an explicit missing listing means no Auction record, not invented timing. A missing/unavailable feed is unavailable, never a seeded end timestamp.

Cursor v1 is a bounded, non-authorizing position tied to normalized filters, sort, page size and a 24-hour publication window. Newest/price use deterministic key-plus-listing-ID order; ending-soon carries the owning Auction cursor. Withdrawal/visibility and current fence reads run again on continuation. This is not an immutable export snapshot: rules/stock can change, requiring a fresh first-page search.

A request scans at most 96 Catalog candidates or three bounded timing pages, hydrates in four-record groups, and returns at most 24 cards. An exhausted scan budget with unknown remaining matches returns an explicit unavailable outcome, not a false empty market. Wire DTOs omit detail-only evidence. Database connections are released before upstream HTTP calls. Each dependency has its own timeout, connection/concurrency and circuit budget; the whole search is bounded to 950ms below the same-origin gateway deadline.

## Canonical live history

The adapter consumes published `contracts-auction/core/index.ts` v1: `GET /v1/auctions?listing_id=...` and `/v1/auctions/{id}/history?after_sequence=...&limit=50`. It validates the closed public snapshot/history DTOs, uses the history response's canonical snapshot, translates `live` to `open`, and converts integer prices exactly. Seller-private `reserve_minor`, maxima and raw bidder references are rejected. Only a successful empty list means not_started; an absent endpoint is unavailable.

A raced latest-history window is resynchronized at most once inside an 850ms total deadline. Ordinary v1's authoritative full revision binds `ends_at` and serves as the shared end-version token; no independent extension is invented. The viewer polls at most once/second while foregrounded/online, backs off failures to eight seconds and rereads canonical time/revision on reconnect. Regressing snapshots cannot overwrite newer state. The countdown uses a monotonic server anchor, not device wall time; reaching zero cannot declare a winner or payment.

Private maxima and raw bidder identities never enter the public model, notices or logs. Optional sale slots load only after a current public/available detail read and remount on access-context rotation. Their owning domains retain all command permissions and business state.

## Proofs

Registered JSON and isolated database/HTTP fixtures are explicit contract-test examples, not startup data or final bid-acceptance evidence. See `tests/lanes/L04/README.md` for recorded checks and connected-service acceptance gates.
