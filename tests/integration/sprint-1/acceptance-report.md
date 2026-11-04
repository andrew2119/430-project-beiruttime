# Sprint 1 cutoff report — BT-91

4 November 2026. Stopped remaining acceptance work on instruction at 21:20 Beirut. **This is not a full demo acceptance sign-off.**

## Verified
- Built and started all nine current domain runtimes and web with Docker Compose, using shared PostgreSQL and nine separate fresh proof databases. All ten application containers became healthy; existing shared containers were untouched.
- Real browser registration; audited first-operator CLI and refusal of a second invocation. Real HTTP onboarding of labeled sample dealer/brand, scoped staff grants, private-seller submission/review/approval, and simulated contact verification.
- Six labeled sample listings published with licensed photographs through actual Catalog/Pricing/Orders operations. No paid, inspected, received, or completed outcome was seeded.
- Fixed auction creation, then created real open and scheduled auctions with Orders fences. Two buyers placed manual/private-maximum bids: USD 100 → 110 → 120 → 160 → 200 → 210. Equal maximum retained the earlier leader; public history omitted confidential maxima. Actual owner-private outbid notices were recorded.
- Two buyers raced Buy Now: exactly one awaiting-payment reservation, retained quote reference and exact total; other buyer denied. Sample USD 180 quote: buyer fee 5.40 (3%), payable 185.40, seller commission 9.00 (5%), seller net 171.00. No charge claimed.
- Real business staff published service-directory profiles, buyer persisted a servicing choice, cross-business write was denied, and a private brand-request draft was saved.
- Docker tests: Identity 39 passed; Orders/L08 39 passed; Auction/L05 101 passed; targeted Communications/notice tests 20 passed. The broad Communications/L05 invocation has an existing cross-runtime test-collection/import prerequisite; the relevant notice suite was run directly instead.

## Fixed and published
- Identity: permanent, audited, concurrency-safe first-operator command; corrected its registration instructions. https://github.com/andrew2119/430-project-beiruttime/pull/18
- Auction: adapt canonical Catalog physical-watch/organization fields and verify registration before fencing; fixes the auction-create 503. Communications: align bid-notice payload with actual Inbox provider model. https://github.com/andrew2119/430-project-beiruttime/pull/19
- Orders: organization-scoped business receipt-read permission; expose retained `quote_id`; preserve adapted client's timeout so the outbox worker can start. Integration evidence accompanies https://github.com/andrew2119/430-project-beiruttime/pull/20

## Not checked / still open
- No complete English/Arabic, light/dark, desktop/390px phone browser matrix, full screenshot set, or professor demo script. One exploratory desktop capture is not acceptance evidence for that matrix.
- Prices-page rendering of the retained reservation quote, browser-driven seller editor/disclosure/upload, dashboards, consent, option selection, technical intake/custody, operator moderation, and full browser bid/reconnect/exclusivity journeys remain unverified.
- Receipt permission regression is covered by isolated scoped/cross-business tests, not a real business custody walkthrough. No physical custody was fabricated.
- Existing bid notices retain retry backoff. Corrected Inbox delivery was observed for an accepted notice; complete outbid Inbox delivery/drain was not awaited at cutoff. Generic informational events also remained pending against unsupported receivers; no all-outboxes-drained claim.
- Repeated sign-in during preparation encountered temporary unavailability; broader rate-limit/UI recovery behavior was not investigated.
- Later payment, auction closing/winner, expert inspection, production, completed service and payouts remain out of Sprint 1 scope. Railway deployment was not attempted.

Proof logs and private temporary sessions remain only in ignored `artifacts/accept/`; no credentials are included in committed evidence.
