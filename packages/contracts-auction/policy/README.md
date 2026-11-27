# Auction policy v2 — fixed scheduled deadlines

Supersedes v1 extension and new auction-purchase admission under the revised auction rules. Source: `bt/bt-s2-l12`, base `dd163d8`; revision candidate, not connected acceptance evidence.

## Fixed end and reserve

`auction.policy.accepted-bid.v2(state)` is pure and synchronous, invoked inside the canonical Auction transaction. Compatibility hooks `auction.policy.accepted-bid.v1` and `auction.extension.v1` use the same fixed-end implementation. Every accepted manual/proxy bid, including a private ceiling-only raise, must precede the server deadline. Output retains the original scheduled deadline and `end_version` and always reports `extended: false`. Legacy stored extension identifiers never activate an extension. New extension configuration is rejected. Only final public price with at least one accepted bid can meet reserve; an unused private ceiling cannot.

When supplied, `scheduled_ends_at` is the authoritative original deadline, including when a retained `ends_at` differs. The returned `ends_at` is that original deadline; `end_version` is unchanged. An absent original deadline uses `ends_at` for compatibility. Both timestamps require an explicit offset. Equality is closed, and refused evaluation does not mutate either input.

Operation lookup: `auction.policy.reserve-met.v1` consumes `ReserveBasis` and returns a boolean. The basis accepts only integer USD cents, a positive optional reserve, and a nonnegative accepted sequence. Invalid or missing facts fail validation; they never become a positive reserve result. Neither this hook nor the accepted-bid hook writes a receipt or owns an allocation. Repeating the same pure input gives the same result. The canonical transaction must supply current serialized facts; stale revisions, denied admission and lost-response recovery remain its responsibility. A timed-out provider is unavailable, never a locally inferred winner.

Public `GET /v2/auctions/{id}/policy` contains schedule, server time, mode, frozen economics and reserve presence, never reserve amount or comparison. Current owner-only `GET /v2/seller/auctions/{id}/policy` adds private reserve status. The seller's current publication permission and business scope are checked on every read. The old public GET is a fixed-end projection; the old PATCH refuses configuration with `fixed_end_policy`. Reserve/rules editing remains the canonical rules authority's job.

## Auction purchase exclusion and historical reads

`POST /v1/auctions/{id}/prebid-buy-now` authenticates an individual buyer, then refuses any new operation with `auction_purchase_removed`. An exact replay of an already persisted request returns its historical outcome, not a new reservation. Actor-owned `GET /v1/prebid-operations/{key}` and `GET /v1/auctions/{id}/my-prebid` stay reachable. Private quote-basis reads remain for existing records only, including legacy currencies; they cannot authorize a new commitment or reinterpret historic money. Fixed-price purchase routes are unchanged.

The UI contains no auction-purchase quote constructor, purchase button, price or extension controls. Historical pending results remain visible; they are not a checkout or reopening promise. Reserve/schedule draft state stays in memory across locale changes; private reserve is not stored in browser storage.

## Canonical cancellation / closing handoff (L13/L14)

L12 supplies fixtures, not a second close/cancellation authority. L13 owns seller cancellation and no-sale close; L14 owns the shared auction lock and canonical mode changes. Under that lock, cancellation with zero accepted bids and first accepted bid are mutually exclusive. After any accepted bid, deny ordinary cancellation. At server time >= scheduled end, reject bids even with no bids and close once with no winner/order. Cancellation preserves history and never frees an uncertain financial hold. Link the seller to the existing listing-management cancellation/withdrawal flow, not a new L12 mutation.

## Historical pending purchase handoff

A restart/timeout retains the original operation, remote key, allocation and financial hold. Reconciliation reads the exact Orders operation only; a 404 MUST NOT POST a new allocation. Record schedule state separately as `ended_legacy_review` at or after the original end, irrespective of unresolved money. Never transition back to bidding or change `ends_at`.

An exact successful historical allocation may be acknowledged under the canonical lock without reopening. A denied allocation is not evidence of no payment attempt or a released physical fence. L13 must publish an Orders-authoritative, stable-key attempt-aware resolution/release receipt before L12 can acknowledge release. Until then, known refusal is `legacy_release_pending`; missing/unknown money is `legacy_outcome_pending`, both held. A confirmed no-attempt/declined-only release resolves to no sale via L13/L14, never via local fence SQL. No fixture is release authority. Non-USD historical commitments stay unchanged and held for restricted reconciliation, outside active customer totals.

Versioned historical readers `GET /v2/prebid-operations/{key}` and `GET /v2/auctions/{id}/my-prebid` return `LegacyOperationSnapshot`: version 2, captured scheduled end, `within_schedule|ended_legacy_review` and financial state `held`. They derive schedule state from server time even before the worker runs. Existing v1 reads and exact POST replay stay reachable. The additive legacy-review migration retains all original request/allocation bindings, backfills only schedule/review metadata, and prevents their later mutation. Known refusal stays `legacy_release_pending`; a contradictory later success stays `legacy_conflicting_outcome`, not another sale. No new allocation POST exists in the worker. Leased review facts commit atomically with the module record; the v2 notice destination stays inactive until subscribed.

Consumes the revised `auction-kernel/v4` fixed scheduled-end/private-state freeze and `orders-commitment/v3` no-new-prebid/attempt-aware release freeze. Where the new canonical scheduled-end column exists it wins; legacy prebid records had no accepted bids and therefore no bid-driven extension. L12 never mutates canonical close/cancellation state or any Orders fence.

`fixtures.json` provides fixed boundaries, public-price reserve, exclusion, cancellation race and ended-review cases. These are deterministic examples only. Focused checks and commit provenance are tracked separately; Docker, connected cancellation/close, financial release and browser evidence remain owed.
