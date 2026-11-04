# Auction integration v1 — owning-provider details still needed

The single Auction engine, actual L06 hook integration, authenticated outbox and Communications bid-notice module are implemented and tested against restricted PostgreSQL databases. Runtime behavior fails closed; transport fixtures are tests only. The following provider details must be reconciled before the connected seller/bid/Inbox browser demo.

## Catalog publication proof (L03/L04)

The published Catalog public view is a same-service read seam, not cross-service SQL. Auction will consume the owner-defined visible `GET /v1/listings/{id}/publication` proof once its exact HTTP DTO is published. Please specify the wire fields for listing ID, canonical seller subject, represented organization, physical watch ID, publication revision, published/visible status, immutable registration/sale mode and demo marker. The public view currently documents `physical_watch_id` and `organization_id`; Auction's provisional fixture used `watch_id` and `seller_organization_id`, so an explicit adapter is required.

Auction must not require an independent physical-watch authentication pass before opening. Current `identity.listings.publish` capability plus the canonical published visible record is the seller/publication gate; private watch authentication happens after purchase. A missing/hidden proof is not sale authority. Orders separately confirms the physical fence.

## Pricing fee preview and admission proof (L07)

Please publish the exact create/read/validation routes and wire DTOs for an owner-private Auction bid quote. Required semantic bindings are current buyer, listing, auction, Auction revision, exact bid minor units/currency, displayed Auction rules and unexpired valid quote. Keep Pricing fee-policy version distinct from Auction's ordinary/increment rule version if they have separate meanings. A fixed-price reservation quote must never accidentally authorize an Auction bid.

Current provisional requests are POST `/v1/quotes` and GET `/v1/quotes/{id}` with buyer Bearer, bounded clients and operation keys. They will be adapted to the provider's frozen version. Frontend rejects malformed, non-integer, unbound or stale previews instead of displaying invented fees, and stays Not confirmed until the stored Auction acknowledgement is recovered.

## Canonical Inbox writer / event dispatcher (L07)

The exact Auction envelope and notice payload are in `auction-events/README.md` and `bid-notices/README.md` in the shared handoff. L05 currently owns Communications `/internal/v1/events` for `auction.bid-accepted.v1`, persists required accepted/outbid notices atomically with the consumer receipt, and durably bridges to the requested idempotent `POST /internal/v1/notices` writer using a Communications service token. Please publish the actual Inbox writer route/DTO, or the runtime event-dispatch seam if Inbox centralizes the receiver, so no duplicate route is introduced. L05 will adapt its owned module, never patch Inbox.

The complete tested L05 module is also published at `bid-notices/module/`, mapping unchanged to `services/communications/modules/bid-notices/`, for the Communications runtime to integrate uncommitted before merge. It is not a second service. Shared Auction core Python contracts require the L05 contract registration and both provider contract subtrees; a copy of the registration is at shared `registrations/L05.json`.

## Current verified contact (L02)

The businesses/contacts handoff declares owner-private GET `/v1/contacts`, but not its JSON shape. Please publish the exact response fields proving a currently verified contact, or a minimal owner-private boolean readiness DTO. Auction only needs current verified/not-verified state; no recipient, code or pending address is stored, logged or emitted. A pending contact must never qualify. The current provisional status call will be replaced rather than guessed from a recipient field.

## Browser session return (L01)

The published `safeReturnPath` allowlist currently omits `/seller/auctions`, so the real shared helper returns `/account` instead. Please add that owned URL in the provider and republish; L05 does not edit the copied provider. Account/organization changes cancel transport and discard private confirmations; server permissions remain authoritative.

## Already reconciled

- L06 pure calculation is invoked in the sole Auction transaction, with normalized empty opening state, retained manual caps, earlier equal-cap sequence, bounded automatic cap responses and no private state in public history/events.
- L08 current authenticated internal fence/read endpoints are used with source-bound lost-response reconciliation. Unknown/competing modes cannot open an auction.
- Seller capability is canonical Identity `identity.listings.publish`, including only the exact freshly selected organization grant. Buying uses the fresh Identity buyer capability; no invented auction-only grant is required.
- Timing reads are canonical, bounded and public; explicit none.v1 extension policy never fabricates an extension, winner or sale.
