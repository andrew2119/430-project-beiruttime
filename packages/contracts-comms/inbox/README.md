# Communications inbox v1

L05's bid-notices module owns `/internal/v1/events` for `auction.bid-accepted.v1`. Inbox registers its own authenticated **`/internal/v1/inbox/events`** under a distinct authenticated route. Pricing's destination adapter sends its durable events there. No central event hook or competing receiver is required; modules still join the one Communications runtime/database.

The receiver is generic over the contracts-core EventEnvelope but accepts only owner-registered exact `(producer,event type)` pairs from `events.py:handlers()`. New producers must supply their exact event names, bounded payload schema and deterministic fixture for registration; unknown types are refused, not silently acknowledged. A committed `{accepted:true}` means registered receiver work was durable, not that a person was notified. Duplicate envelope IDs return `{accepted:false}` without repeating effects. Authentication/policy/schema failures are 401/403/422; configuration and transient failures are retryable 503/500 with no committed receipt. The full shared ingress note is published separately as `communications-events`.

Inbox V1 input follows `models.py:NoticeInput`. Event ID deduplicates transport; `(recipient,source,occurrence_id)` deduplicates the historical occurrence. Required outbid/payment/case categories ignore optional preferences. No arbitrary HTML or URL is accepted. Current delivery includes `pricing.quote-created.v1` and `pricing.quote-reviewed.v1`; additional typed notice categories remain versioned provider integration points, not fabricated startup activity.

## L05 bridge

`POST /internal/v1/notices` requires a service JWT `sub=communications,type=service,aud=communications`. It accepts the frozen Bid-notices V1 body `{id,recipient_id,kind:bid_accepted|outbid,resource_type:auction,resource_id,href,created_at,data:{current_minor,currency,ends_at,sequence},resource_revision?}` (`accepted` is also accepted as a compatibility spelling). Unknown fields, including private maxima, are refused. Inbox receipt and deduplicated notice commit atomically. `href` is syntax-checked but never trusted: opening resolves Auction's canonical current listing projection. Missing legacy resource_revision is explicitly null, never invented from sequence. Both accepted and outbid bridge notices are required.

## Owner APIs

`GET /v1/inbox?cursor=<notice UUID>&limit=20`, `POST /v1/inbox/:id/{read|clear}` with `{expected_revision}` and Idempotency-Key, GET/PUT preferences, and `GET /v1/inbox/:id/destination`. Each request rechecks current Identity and owner scope. Represented-organization sessions cannot open a personal inbox. Destinations recheck their owner API: a historical notice cannot grant current access. Listing never implicitly marks read; clear is a distinct durable marker. Canonical polling is bounded while personal-stream delivery is unavailable.

Buying APIs: `/v1/buying/drafts` POST/GET; `/:id` GET/PUT; `readiness?reservation_id=&quote_id=`; `payment`; `drafts/:id/{send|accept}`. Payment/send/accept always deny `capability_not_released` in Sprint 1. A saved owner/revision-bound draft is not an offer sent or accepted.

Readiness consumes owner-authorized Orders `GET /v1/orders/:id` -> `{order,history}` and projects only the current buyer's order ID/state/currency/total/deadline/revision/quote_id, never history or custody evidence. The retained quote_id is auto-resolved through Pricing and its owner/currency/total/source/deadline bindings are checked. A different selected quote denies 409, never silently substitutes. If the Orders projection has not supplied its quote_id yet, the honest state is `binding_unavailable`; the real reserved total remains visible, but an unrelated preview is never presented as that order's fee basis.

Outbox invalidation intent remains transactional under destination `personal-invalidation`. No public event bus or invented order state is exposed. The web view currently uses canonical polling rather than claiming a delivered personal stream.

V2 adds immutable source-fact deduplication, authenticated outbid/quote subscriptions and payment v3 availability receipts. See [the v2 contract](V2.md) for lookup and retry semantics. Inbox lists include the server total of uncleared notices, separately from unread count and page size.

Personal invalidation delivery is deferred. Pending intents stay pending while
canonical polling serves current state. Stream delivery requires an owner-scoped
private transport and an exact source and type subscription before the
destination can be enabled.
