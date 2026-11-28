# Exact quotes v1

`POST /v1/quotes` accepts QuoteRequest, Idempotency-Key and a current personal buyer Bearer token. `GET /v1/quotes` lists current owner snapshots with pagination; `GET /v1/quotes/:id` is owner-only. Active prices are bounded integer USD cents, never floats or separator-bearing strings. Archived quotes keep their original amounts and currency and are excluded from both reads. Snapshots retain subject/revision, purpose, currency, policy, commission basis, rounding, creation/expiration and separately acknowledged review time. Database constraints balance totals and prohibit rewriting/deleting retained snapshots.

Use `usd-v2` (policy revision 2) for active watch quotes. Quotes are marked `sample:true`; collection is simulated. USD 500000 cents + 15000 buyer fee = 515000 payable. Separate sample seller commission is 5% of base and net is base minus commission. Shipping/tax are explicit sample zero, FX is not applied. Half-up rounding is integer-only; both exponents are included in the policy snapshot.

## Proposed versus authoritative listing basis

`source:'sample'` (default) is a non-binding proposed price preview. Its `source_verified:false` can NEVER authorize an Orders reservation. `source:'listing'` is allowed only for purchase and reads Catalog `GET /v1/listings/:id/publication` over a dedicated bounded client before opening the Pricing write transaction. This canonical publication contains `id,revision,status,physical_watch_id,seller_id,facts:{sale_mode,currency,price_minor}`. It must be a currently published fixed-price listing with exactly the requested ID/revision/currency/price. Changes deny 409, not silent substitution; outage/malformed publication stays unavailable. Only that path creates `source_verified:true`. The fee policy is still clearly labeled sample even when its listing price basis is verified.

`POST /v1/quotes/:id/review` takes the original QuoteRequest plus quote_revision and payable_minor. It acknowledges that exact retained version, NOT charge authorization. Changed bindings deny; expiration at equality denies and requires a new preview. An exact replay retains the first review outcome after expiry. The additive default source field preserves original sample-command idempotency digests.

## Other command consumers

Seller publication reads the owner-only snapshot and must bind its own still-current draft ID/revision, exact USD base amount, purpose `purchase`, source `sample`, expiry and schedule `usd-v2`. Map `subject_id` to listing_id, `subject_revision` to listing_revision and `schedule_id` to fee rules_version; `sample:true` is the explicit demo-policy marker. This preview does not grant seller verification or publication permission.

Auction reads that same owner-only snapshot and must bind purpose `bid`, bidder owner_id, subject_id = its auction ID, subject_revision = the expected current Auction revision, exact proposed amount/currency and unexpired time inside its own admission guard. Auction's immutable listing reference supplies the listing binding; this does not expose a private maximum to other actors. Auction must not use the purchase-only Orders validation endpoint.

## Orders validation (exact L08 V1)

`GET /internal/v1/quotes/:id/validation` requires the current buyer's Bearer token. A proposed/sample basis denies `quote_not_authoritative`. A listing-bound purchase quote must still be unexpired, owned by that buyer, and match a freshly read canonical Catalog publication. The response is exactly `{quote_id,buyer_id,listing_id,listing_revision,currency,total_minor,expires_at,status:'valid'}` where total_minor is the retained buyer payable. This is a soft-reservation prerequisite, not payment, receipt or payout authority. No public gateway exposes this internal endpoint.

Outbox: Pricing sends authenticated `pricing.quote-created.v1` and `pricing.quote-reviewed.v1` to Communications **`/internal/v1/inbox/events`** using a destination-path adapter around the foundation bounded relay. It does not contend with L05's `/internal/v1/events` receiver. Missing credentials leave intent durable. The first event carries NoticeInput; the second acknowledges review only and cannot manufacture a paid notice.
