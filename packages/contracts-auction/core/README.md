# Auction core v1

All money is integer minor units (USD cents, LBP piastres), bounded to 9,000,000,000,000,000. Instants are UTC. Admission uses the database clock after obtaining the auction transaction lock; client timestamps have no priority. Public snapshots never contain actor IDs, private maxima or reserve amounts.

## HTTP

- `POST /v1/auctions`: seller creates from a currently visible published listing and a current listing-publish grant. `Idempotency-Key` required. Fields: listing_id, currency, opening_minor, increment_bands [{from_minor,step_minor}], reserve_minor (optional), starts_at, ends_at. Ordinary rules version `ordinary.v1`; no automatic close or winner implied.
- `GET /v1/auctions?listing_id=<uuid>`: canonical public snapshots.
- `GET /v1/seller/auctions`: currently authorized seller/org-only lots, including private reserve_minor. This private field never appears in public snapshot/history DTOs or notices.
- `GET /v1/auctions/{id}`: public canonical snapshot including server_time, revision, accepted_sequence, current_minor, next_minimum_minor, masked leader, starts_at, ends_at, status, rules_version, high_value_minor, reserve_set and extension_policy (`none.v1`).
- `GET /v1/auctions/{id}/history?after_sequence=0&limit=50`: bounded masked canonical history, sequence cursor and server time. Poll at most once a second; reconnect rereads snapshot. No public private-account fields.
- `PATCH /v1/auctions/{id}/rules`: same fields except listing_id; `If-Match` numeric revision and Idempotency-Key required. Only before first accepted bid; same Orders commitment and current Catalog prerequisites required.
- `POST /v1/auctions/{id}/bids`: amount_minor, fee_quote_id, expected_revision; Idempotency-Key required. Outcomes stored once per subject/key: operation_id, status succeeded/denied, code, auction_id, revision, accepted_sequence, current_minor, next_minimum_minor, server_time. HTTP 200 on stored success or denial. Dependency failure is 503 and NOT a bid acknowledgement. GET `/v1/auctions/{id}/operations/{operation_id}` is owner-private reconciliation; GET `/v1/auction-operations/by-key/{key}` recovers lost acknowledgements.
- `GET /v1/my-bids?limit=100&cursor=<uuid>`: owner-private `{items,next_cursor}`. Each item includes canonical AuctionSnapshot plus auction_id, buyer_id (current subject only), current_price_minor, my_status leading|outbid, and next_action review_bid|auction_ended. Snapshot status remains live|scheduled|ended, not a fabricated result. A non-null cursor means another bounded page exists. No ceiling or invented demo marker is returned.

## Frozen L06 hook: auction.proxy.v1

The synchronous pure callback is `calculate(state: dict, command: dict) -> dict`. It executes under the one Auction transaction lock. No IO, SQL, randomness, clocks or commit. Runtime exposes async `request.app.state.auction.submit(request, auction_id, command, kind='maximum')`; L06 route supplies a command with the same fields as manual admission (amount_minor is private ceiling). Runtime owns all eligibility, idempotency, fee binding, receipt ordering, persistence, projection and events. L06 must not build a parallel engine.

Empty pure state uses current_minor=opening_minor, sequence=0, leader_id=null and no maxima; persisted/public empty lots keep current_minor=0. Manual caps are persisted even before the proxy module arrives, so loading it never invents historical state.

State: `{current_minor, opening_minor, leader_id: str|null, sequence: int, increment_bands: [{from_minor,step_minor}], maxima: [{bidder_id: str, amount_minor: int, sequence: int}]}`. Command: `{kind: 'manual'|'maximum', bidder_id: str, amount_minor: int, sequence: int}`. Result: `{leader_id: str, current_minor: int, maxima: [{bidder_id,amount_minor,sequence}], bids: [{bidder_id: str, amount_minor: int, automatic: bool}]}`. Result must be deterministic, non-decreasing, bounded, respect maxima and preserve earlier sequence on ties. Automatic responses may stop at a ceiling below a full increment; an equal automatic cap response may retain the earlier leader after an equal manual bid. Manual admission itself always requires the next full increment. Runtime validates result, saves all public-price transitions with unique sequence, and emits a single leader-displacement event. No maximum fields enter public DTOs/events/logs. Manual-only operation works with no hook; maximum commands fail unavailable until the hook is installed. An existing private maximum never silently bypasses the hook.

## Authenticated outbox

Producer `auction`, audience `communications`, envelope type `auction.bid-accepted.v1`. Data is strictly `{auction_id,listing_id,sequence,revision,current_minor,currency,ends_at,bidder_id,previous_leader_id,leader_id}`. Recipient IDs exist only in authenticated service delivery. Public history is separately projected. Communications deduplicates by envelope ID plus recipient and notice kind. Every accepted operation sends accepted notice to submitter; outbid goes only to a displaced leader. Required inbox delivery ignores optional channel preferences.

## Current capability and organization scope

Seller create/update/read requires the canonical Identity permission `identity.listings.publish`: individual approved private sellers or the exact represented official-business grant. Optional `organization_id` query selection is revalidated by Identity `/internal/v1/principal?organization_id=...`; no caller-provided organization header grants authority. Resource ownership must match that verified selected organization. Business-member self-bids are denied even when bidding personally. A fresh Identity `buyer` role is the published buying capability; suspended/revoked sessions cannot supply a current principal. No invented `auction.manage`/`auction.bid` grant is required from Accounts.

## Dependency contracts (fail closed)

Catalog's visible publication HTTP proof must return the canonical seller subject/org and physical watch ID. Its exact owner-defined DTO is still required; the current provisional `/v1/listings/{id}` fixture is not a production fallback. Independent watch inspection is not an auction-opening prerequisite. Orders `GET /internal/v1/watches/{watch_id}/fence?source_id={auction_id}` and `POST /internal/v1/watches/{watch_id}/fences` use authenticated Auction service tokens. A watch registered for auction must be fenced to this exact source before opening. The fence command uses current Orders expected_revision and a deterministic auction-create operation key; a lost remote response is reconciled through source_matches on canonical reread. Unknown/timeout never opens a second sale. Pricing quotes v1 bind the current buyer (`owner_id`), Auction ID (`subject_id`), Auction revision (`subject_revision`), purpose `bid`, currency and exact `price_minor`. The retained balanced sample-policy snapshot must have `reviewed_at` and be unexpired. Explicit `/v1/quotes/{id}/review` confirmation precedes admission; it is not payment. Pricing schedule/revision are distinct from Auction ordinary rules/revision. Expiry is checked again against database time after prerequisite calls. Identity current principal is authoritative; high-value contact verification is additionally checked. Adapters and deterministic transport fixtures live in the lane tests; they are not production fallback data.

An authenticated buyer can read `GET /v1/auctions/{auction_id}/bid-receipts/{sequence}`.
The receipt returns `event_id`, `auction_id`, and the accepted `sequence` only
when the current subject submitted that admission. Other subjects receive 404.
The source binding is retained in the durable outbox, including immediately
beaten challengers; public history rows need not map one to one to admissions.

`GET /v1/auctions/{auction_id}/deadline-boundary` is seller-private and uses
current authentication. It returns the stored `ends_at`, identical `evaluated_at`,
`auction_id`, `revision`, `accepted_sequence`, and the production window denial
`code` evaluated at that deadline. It is a policy read, not a submission clock
or permission to bid. Missing auctions and other scopes return 404.
