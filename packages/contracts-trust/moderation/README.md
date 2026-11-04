# Trust moderation V1

Trust owns `/v1/moderation/reports` (POST), `/v1/moderation/cases` (GET), `/v1/moderation/cases/{id}` (GET), and case `/claim`, `/release`, `/decisions`, `/appeals` commands (POST). Commands require an Idempotency-Key; case commands also require integer If-Match. The first saved outcome binds actor, route, request body and expected revision; uncertain retries retain the same key. Current Identity permissions are `moderation.review`, `moderation.decide`, and separate `moderation.assign` for reasoned assignment release; reporters may read and appeal their own case. Reviewers cannot review reports about themselves or reports they submitted. Assignment-capable operators may see safe queue summaries and release an abandoned/revoked-reviewer assignment with reason/revision/audit; this never grants them evidence access. The next independent reviewer must claim the case. Previous assignment loses detail access immediately on the server.

## Provider dependencies

- Identity `GET /internal/v1/principal`: foundation CurrentPrincipal V1.
- Catalog authenticated `GET /v1/listings/{id}/report-subject`: minimal response includes `id` (or `listing_id`) and `seller_id` UUIDs. Reports of a hidden listing remain possible only to its owner or real authorized transaction parties. This is the published L03 seam, not L04's public detail endpoint.
- Communications `GET /v1/messages/{id}`: authorized response includes `sender_id` UUID; absent/denied messages cannot be reported by unrelated users.
- Identity `GET /v1/accounts/{id}/report-subject`: authorized minimal response includes `subject_id` equal to the requested UUID. Missing lookup is unavailable/not found, never an invented account case.
- User report targets are UUIDs, never public evidence previews.

## Durable event: trust.moderation.decided.v1

Producer `trust`; foundation authenticated EventEnvelope. Data: `case_id`, `target_kind` (listing/user/message), `target_id`, `action` (warn/hide/suspend/reinstate/dismiss), `revision` (monotonic case revision), `preserve_transaction_duties: true`. No private evidence or free-text reason is sent. Catalog consumes listing hide/reinstate and applies visibility without deleting the listing or altering allocations, custody, payment or dispute duties. Identity consumes user suspend/reinstate only with transaction/support access preserved: a marketplace suspension must not abandon active custody, payment, disputes or the correction/appeal route through blanket sign-in denial. Communications consumes message hide/reinstate. A command records a durable decision, not successful downstream application: case `delivery` remains pending until the destination acknowledges the outbox event. Consumers must reject older case revisions and deduplicate event ids.

Delivery uses per-dependency bulkheads and an RS256 service token, subject `trust`, destination audience, issuer `beirut-time-identity`, from `BT_TRUST_SERVICE_PRIVATE_KEY`. The public verification key belongs in each receiver's `BT_SERVICE_AUTH_PUBLIC_KEY`. Missing credentials retain pending work; no unsigned delivery is attempted.

Fixtures in this directory are transport examples only, never authoritative application records.
