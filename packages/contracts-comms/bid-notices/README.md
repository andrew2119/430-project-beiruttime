# Bid notices v1

Auction emits `auction.bid-accepted.v1` through authenticated durable outbox to Communications `/internal/v1/events`. L05 owns this opt-in receiver in `services/communications/modules/bid-notices`; other Communications modules must not register that same HTTP path. Only service RS256 tokens with `sub=auction`, `type=service`, `aud=communications`, current exp/iat and expected issuer can publish.

Accepted data: auction_id, listing_id, sequence, revision, current_minor, currency, ends_at, bidder_id, previous_leader_id, leader_id. Unknown fields (including maxima) are refused. Required outbid recipients derive solely from the displaced leader, not caller preferences. Notice IDs are deterministic per event/recipient/kind; receipt plus all notices are committed in one transaction. Accepted and outbid messages contain canonical current price/end references, never a private ceiling.

`GET /v1/bid-notices` is owner-private, bounded and uses fresh Identity principal. `GET /v1/bid-notices/{id}` denies other owners by returning 404. Opening a notice fetches Auction `GET /v1/auctions/{id}` through a bounded client; the historical event is never a current fee preview or bid permission. An unavailable canonical read says unavailable while retaining the original notice.

The published `communications.inbox.v1` bridge is `POST /internal/v1/notices`, authenticated with a Communications service token. Payload matches Inbox's frozen Bid-notices V1 model: `{id:notice_id,recipient_id,kind,resource_type:'auction',resource_id:auction_id,href:'/watches/'+listing_id,created_at,resource_revision:null,data:{current_minor,currency,ends_at,sequence}}`. The provider makes accepted/outbid notices required and derives safe navigation from a current canonical Auction read. It carries bounded references only, not arbitrary URLs or private ceilings. The stable occurrence and operation keys survive durable retries; optional channels cannot suppress required notices. Storage acknowledgement does not claim channel delivery or a winning/paid result. The owner-private bid-notice read still returns its relative `/watches/{listing_id}` link and canonical current-state reread when Inbox is temporarily unavailable. Generic Inbox event ingestion uses `/internal/v1/inbox/events`, not L05's Auction receiver. No public notification publishing endpoint is introduced.

`GET /v1/bid-notice-receipts/{event_id}` requires current recipient authentication.
It returns `event_id`, `notice_id`, `auction_id`, `sequence`, and `inbox_id` for
that recipient's bid acceptance. Missing or other-recipient events return 404.
`inbox_id` is null until the recipient Inbox row has committed. It is read from
the durable Inbox binding, independently of bridge attempts or delivery markers.
The unique event/recipient/kind and recipient/source/occurrence constraints keep
both identifiers stable across replay, including an immediately beaten bidder.
