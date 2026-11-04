# Catalog listings v1

All commands use a current Identity principal, Bearer access token, `Idempotency-Key`, and (except create) integer `If-Match` revision. Optional `organization_id` query selects a business only after Identity verifies that current membership and exact organization grant; it is not caller-issued authority. No caller actor/organization header is trusted. Any current signed-in individual may prepare own private drafts/media/workspace. `identity.listings.publish` is required for publication and for representing official business stock. Individual permissions stay on principal.permissions; business permissions/roles must belong to the selected organization_grant. `catalog.demo.import` is an individual permission used only with `BT_ENVIRONMENT=demo`.

- POST `/v1/seller/listings` accepts CreateDraft from v1.py, returns Listing.
- GET `/v1/seller/listings?limit=30&before=<uuid>` returns owner/org-scoped `{items,next_cursor}` (UUID descending).
- GET/PUT `/v1/seller/listings/:id` read/save complete draft facts. Incomplete drafts persist; publication reports missing fields.
- POST `/v1/seller/listings/:id/media`: raw bounded JPEG/PNG or private PDF. Query `kind=public_photo|private_document`; public watch-only photos require `public_safe=true`. Direct-service callers may equivalently use X-Media-Kind and X-Public-Safe headers. Query metadata crosses the existing gateway without adding trusted headers. Returns `{asset_id,kind,listing}`. Max 8MB/file, 20M decoded pixels, 12 public photos + 5 private documents, 40MB/listing. Public photo variants: thumb=320/card=640/detail=1600 max edge, aspect-preserving metadata-free JPEG.
- PUT `/v1/seller/listings/:id/gallery` accepts `{photo_ids,cover_id}`; only same-listing public photos are valid.
- GET `/v1/seller/listings/:id/media` lists file references; GET `/v1/seller/listings/:id/media/:asset` is an authorized, attachment-only byte read.
- POST `/v1/seller/listings/:id/publish` accepts `{fee_quote_id,rules_version}`. Resumable pending state freezes the revision before remote registration. No SQL transaction stays open across HTTP. One persisted operation identity is reused with Orders even after an ambiguous timeout.
- GET `/v1/listings/:id/publication` returns a minimal public canonical publication proof.
- GET `/v1/listings/:id/photos/:asset/:variant` returns bytes only when published and associated to the public gallery. GET `/v1/listings/:id/photo-credits` returns safe attribution.

## Provider integration requests

Identity: use the foundation CurrentPrincipal and permissions above. A current verified private seller receives `identity.listings.publish`; current onboarded official business grants receive it in that organization's grant. Listing publication does not imply an independent inspection or factory endorsement.

Pricing: GET `/v1/quotes/:id` returning `{id, listing_id, listing_revision, rules_version, status:'valid', ...fee_snapshot}`. Quote creation is owned by Pricing. Catalog refuses mismatched/invalid snapshots.

Orders allocation v1: POST `/internal/v1/watches/register` with a short-lived RS256 Catalog service token (issuer BT_AUTH_ISSUER, audience orders, subject catalog, type service), stable publication operation id in Idempotency-Key, and exact RegisterWatch `{watch_id,listing_id,seller_id,organization_id,listing_revision,sale_mode:'fixed'|'auction'|'seller_base'}`. The listing_revision is the future published revision (draft revision + 1), so the persisted fence binds the actual public revision. Catalog maps fixed_price→fixed and offer→seller_base. Require the direct Availability DTO `{watch_id,listing_id,sale_mode,status:'available',revision}` with exact resource/mode bindings. Unavailable/unknown/fenced registration stays pending, never publicly available. Signing material is deployment configuration, not a user token or a runtime fallback. Final connected proof must confirm this response with the provider.

## Discovery extension seam

Catalog owns a same-service PostgreSQL view `catalog_public_listings_v1` with only published records: `id,seller_id,organization_id,seller_type,seller_label,physical_watch_id,revision,status,facts,photo_ids,cover_id,is_demo,registration,rules_version,published_at`. L04 may query this view within Catalog, and may join `catalog_media` for safe public photo credits (never private_bytes). `facts` matches WatchFacts in v1.py. No cross-domain SQL.

Events use durable authenticated outbox envelopes: `catalog.listing.draft-saved.v1`, `catalog.listing.media-updated.v1`, `catalog.listing.published.v1`. Payloads contain only listing_id/revision/seller_id/organization_id/status/is_demo; consumers reconcile their authorized HTTP view. Auction receives exactly one published intent for auction mode. Communications receives saved/updated/published references. A service signing key is required for relay; a missing key leaves intent durable, never silently delivered.
