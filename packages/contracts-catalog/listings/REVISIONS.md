# Published listing revisions v1

Provider L15; source candidate on bt/bt-s2-l15, baseline 1016d21. Existing publication/listing v1 remains compatible. New browser routes have additive v1 aliases; canonical revision routes are v2.

`POST /v2/seller/listings/{id}/revisions` accepts `{facts:WatchFacts,reason:string(3..200)}` with `If-Match` and stable `Idempotency-Key`. Current owner, selected organization, stock/publication permission and revision are checked. Returns `{id:operation_id,status:pending|succeeded|denied,resource_id,listing}`. GET the same resource returns `{pending_operation_id,items:[{revision,actor_id,reason,before_facts,after_facts,created_at}]}` privately. GET `/v2/seller/listing-edit-operations/{id}` reads the retained outcome; POST that path plus `/resume` retries the exact operation. A known denial allows a fresh explicit user command; an uncertain outcome never rotates its key.

## Source and physical authority sequence

Catalog persists authorized intent before HTTP and captures the current Orders watch revision once. All new edits use `auction-kernel/v3`, including a listing-level hold when no lot exists:

1. POST Auction `/internal/v3/listing-edits/prepare` with operation/listing/watch/base/next revisions and normalized public facts digest, plus `orders_operation_key:operation_id`, captured `orders_expected_revision`, retained `lease_seconds:120`.
2. Confirm exact prepared acknowledgement, then POST `/internal/v3/listing-edits/{id}/dispatch`. Only exact dispatched phase/protocol/Orders key/revision permits invocation. Persist prepared/dispatched facts and `orders_started` before Orders HTTP. Only Auction's dispatch CAS decides lease expiry; Catalog never guesses from its own clock, timeout, 404 or stale prepared replay.
3. POST Orders `/internal/v2/commitments` with `{operation_key:operation_id,source_id:operation_id,watch_id,listing_id,listing_revision,expected_revision,kind:edit,reason}`. The header matches the retained operation key. Require exact succeeded/editing/watch/listing/source/base revision, not just HTTP 200.
4. Commit Catalog facts, immutable history and outbox atomically. POST Orders `/internal/v2/watches/{watch_id}/edit-complete` with `{operation_key:operation_id+:complete,source_id:operation_id,listing_revision:base+1}`. Confirm exact physical completion, then POST Auction `/internal/v3/listing-edits/{id}/commit` with `{listing_revision:base+1}` and require exact committed acknowledgement.
5. A definitive Orders denial still retains Catalog's pending intent until POST Auction `/abort` returns exact terminal aborted scope. Auction independently reads the retained Orders command through its least-privilege `ORDERS_RESOLUTION.md` seam; Catalog supplies no caller proof. Missing/malformed/unavailable proof stays pending, blocks competing edits/withdrawal and emits no price event. POST Auction `/reconcile` handles lost Orders/abort replies. Confirmed expiry before dispatch denies without ever invoking Orders; expiry cannot release a locally dispatched source.

The facts digest is lowercase SHA-256 of complete normalized WatchFacts via `json.dumps(facts,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')`, including all defaults and Arabic text, never private reasons/evidence. Unknown acknowledgements retain the exact intent. After prepare, a remote HTTP error is `503 edit_pending`, not a terminal command denial; Catalog facts/history may already have committed before final acknowledgements. Only the independently confirmed terminal abort clears an uncommitted intent. No SQL transaction spans remote HTTP and no speculative unfence exists.

The additive L15_0002 migration marks existing retained commands protocol 2. Those commands keep their original V2 prepare/commit/key bindings and can use V3's conservative abort/reconcile path. New intents explicitly select protocol 3; retries never silently upgrade a live command.

## Shared local transaction API

Catalog writers borrow `service_app.listing_repository.lock_listing(tx, listing_id, expected_revision=...)` and `require_no_pending_edit(tx, listing_id, operation_id=...)`. They never commit or perform HTTP. The source lock is `listing:<UUID>` then `catalog_listings FOR UPDATE`. Call the pending guard while holding that lock. Withdrawal must reject an unresolved edit before preparing another mutation; physical authority remains Orders' existing commitment kernel, not a second fence algorithm.

Final acknowledgements may remain pending after Catalog commits; restart/browser loss resumes the same operation. Sale-mode conversion is not inferred from fact editing. `catalog.listing.revised.v1` accompanies the actual revision; only an actual committed price difference emits `catalog.listing.price-changed.v1` once with listing_id/revision only. New destinations stay inactive until receivers subscribe. Private reasons/history/serials never enter public events.

Boundary tests include exact dispatch before Orders; expired pre-dispatch lease; lost dispatch/denial/abort replies; independently confirmed denial then fresh explicit retry; malformed expiry after dispatch held; V2 compatibility; competing/stale editors; Arabic digest; and one committed price-change alert. Provider transport fixtures are not connected acceptance. Live denial recovery requires the actual provider-owned Orders read seam.
