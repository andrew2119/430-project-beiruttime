# Auction integration v1

The single Auction engine, actual L06 hook, authenticated outbox and Communications bid-notice module are implemented against restricted PostgreSQL databases. Runtime behavior fails closed. Transport fixtures are tests only; they are not production fallback data.

## Remaining Catalog publication seam (L03/L04)

The published Catalog public view is a same-service read seam, not cross-service SQL. Auction needs the owner-defined visible `GET /v1/listings/{id}/publication` proof's exact HTTP DTO: listing ID, canonical seller subject, represented organization, physical watch ID, publication revision, visible/published state and immutable registration/sale mode. The public view documents `physical_watch_id` and `organization_id`; the provisional transport fixture used `watch_id` and `seller_organization_id`, so the owner-defined HTTP adapter must replace it before the connected demo.

Current `identity.listings.publish` plus a visible published record is the seller/publication gate. Independent physical-watch authentication is a later private-watch purchase step, not an auction-opening requirement. Orders separately confirms the physical sale fence.

## Integrated Pricing quotes v1 (L07)

Buyer Bearer commands create `POST /v1/quotes` with `{subject_id:auction_id,subject_revision:auction_revision,purpose:'bid',currency,price_minor,schedule_id:'sample-v1',source:'sample'}` and a stable UUID operation key. This policy is explicitly labeled sample, not a production tariff. The current Pricing limit is 9,000,000,000,000 base minor units, below Auction's integer storage bound.

After displaying exact buyer fee, shipping, tax and payable minor units, explicit confirmation calls `POST /v1/quotes/{id}/review` with the same request plus `quote_revision` and `payable_minor`, retaining its own UUID key through uncertainty. This review is not payment. The subsequent bid retains a separate key and exact body. A lost bid response reconciles through the owner-private Auction operation read; nothing is optimistically accepted.

Admission reads owner-private `GET /v1/quotes/{id}`, validates the provider snapshot and binds its ID, owner, purpose, Auction ID/revision, exact amount/currency, sample-policy flags and recorded review. Auction ID binds its immutable listing. Pricing revision/schedule are distinct from Auction revision/ordinary rule version. The balanced retained quote must be unexpired, including a database-clock recheck after current prerequisites. Purchase-only validation is never used for bids.

## Integrated Communications Inbox reference v1 (L07)

L05 owns Communications `/internal/v1/events` only for authenticated `auction.bid-accepted.v1`. Generic domain event ingestion uses the different `/internal/v1/inbox/events` path owned by Inbox. L05 atomically persists its receipt and deterministic required accepted/outbid notices, then durably bridges to `POST /internal/v1/notices` using a Communications service token.

The published `communications.inbox.v1` payload is `{occurrence_id:'bid-notice:'+notice_id,recipient_id,kind,resource_id:auction_id,resource_revision:null,resource_owner_id:recipient_id,event_time,required:true,sample:false}`. No arbitrary href, private ceiling, contact or caller-provided recipient enters the adapter. Acknowledgement is durable Inbox storage, not channel delivery or a winning/paid result. The sender preserves its occurrence key through retries. A real running Inbox integration check is still required.

## Integrated current contacts v1 (L02)

High-value admission reads owner-private `GET /v1/contacts`. Both `email_verified` and `phone_verified` must be strict booleans; either current true flag qualifies. Pending challenge metadata and recipient presence never qualify. Malformed/unavailable reads are unavailable, not false acknowledgements. Recipients/codes/pending metadata are never stored, logged or emitted by Auction.

## Other reconciled seams

- L06 pure calculation runs in the sole Auction transaction with normalized empty opening state, retained manual caps, earlier equal-cap ordering, bounded automatic responses and no private state in public history/events.
- L08 authenticated internal fence/read endpoints use source-bound lost-response reconciliation. Unknown or competing commitments cannot open an auction.
- Seller authority is canonical Identity `identity.listings.publish` for the exact freshly selected organization. Buying uses a fresh Identity buyer role, not invented Auction grants.
- The published Identity browser helper now permits `/seller/auctions` returns, distinguishes restoring/signed-out/unavailable and fences callbacks by owner access fingerprint. Provider routes and registrations remain uncommitted integration inputs until the owning branch merges.
- Timing reads are canonical, bounded and public. The explicit `none.v1` extension policy never fabricates an extension, closure, winner or payment.
