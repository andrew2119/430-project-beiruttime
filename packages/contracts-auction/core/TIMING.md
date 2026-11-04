# Auction timing read v1

Canonical public timing comes from Auction, not Catalog timestamps or a browser clock. No actor, private ceiling or reserve amount appears in this read.

## Endings and countdowns

`GET /v1/auctions/{auction_id}/timing` returns `AuctionTimingV1` (TypeScript in timing.ts). All instants are timezone-aware UTC ISO strings:

- auction_id, listing_id: UUIDs.
- starts_at: published start.
- scheduled_ends_at: published scheduled end under the current economic rules.
- current_ends_at: authoritative effective end, including extensions when those are delivered.
- server_time: current database time, used to calculate a client offset.
- status: scheduled before start, live at/after start and strictly before current end, ended at/after current end. Ended is NOT a closed winner, paid order or sold result.
- revision: current canonical Auction revision; any later snapshot revision replaces an older timing snapshot. It may also advance for a bid that does not change the end.
- rules_version and extension_policy: frozen rule identifiers.

**Sprint 1 ordinary auctions explicitly use extension_policy=none.v1. No extension is simulated: scheduled_ends_at and current_ends_at are equal.** Before the first bid the seller may update the scheduled rules under revision control, advancing both. Sprint 2 may extend only the effective end while preserving the scheduled value; the V1 field meanings stay unchanged.

Use `current_ends_at` for countdown and ending-soon order. Retain scheduled_ends_at for disclosed comparison, never as the current countdown after a later effective end arrives. Reread canonical state on reconnect/focus and at bounded polling frequency (no more than once per second per active view). An unavailable read is unavailable, not a locally extended auction or permission to bid.

## Bounded ending-soon and batch read

`GET /v1/auction-timing?status=active&limit=100&cursor=<auction UUID>` returns `AuctionTimingPageV1`: `{version:1,items,server_time,missing_listing_ids,next_cursor}`. Items are ordered by `(current_ends_at,auction_id)` ascending in Auction itself. A non-null next_cursor means more rows are available; do not claim the first page is the complete market. Each page is a fresh canonical read; deduplicate IDs and resync after rule changes/reconnect.

Status filters: active = scheduled or live (not ended); live; scheduled; ended; all. Default active. `limit` is 1–100. All items and the page share one database server time and a repeatable-read snapshot. No cross-service SQL is needed: Discovery may request canonical ending-soon listing IDs, then check its own current listing visibility/filter policy.

For a known Catalog candidate set, use `GET /v1/auction-timing?listing_ids=<comma-separated UUIDs>&status=all&limit=100` (1–100 UUIDs). The same end order applies within those candidates. missing_listing_ids names references with NO Auction record, not rows merely excluded by a status filter or pagination. Missing timing cannot authorize an auction, a sale fence or a bid.

Public BFF paths are `/api/{web|mobile}/v1/auction/v1/auction-timing` and `/api/{web|mobile}/v1/auction/v1/auctions/{id}/timing`; L05 registers these read methods. Service consumers use their own bounded Auction client against the direct `/v1/...` paths. Do not add a cross-service database read or duplicate gateway registration.

The accompanying JSON is a synthetic transport fixture only, not a seeded marketplace bid or auction.
