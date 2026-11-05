# Auction policy / pre-bid purchase proof

## Source boundaries

L12 owns extension-policy, prebid-buy-now, contracts-auction/policy, auction-policy UI and the existing auction-management UI. The canonical Auction engine/kernel/mode migration remains L14-owned; physical allocation and journal remain L13-owned. No consumer source or copied kernel fixture belongs in this lane's commits.

The pure policy hooks support both `auction.policy.accepted-bid.v1(state)` and the initial `auction.extension.v1(state,bid)` alias. Only one is invoked, once per admitted command with public bid rows. A private maximum-only increase does not extend. At 120 seconds remaining, add 120 seconds to **current** end; at the exact end refuse. Reserve uses public price, never a private cap.

Prebid persists its exact operation and `prebid_pending` under the canonical kernel lock before Orders HTTP. A lease-fenced worker reads the same remote operation and retries the same allocation only on a missing operation. Unknown and denied allocations never reopen bidding. Success advances the same canonical mode, stores one private result and outbox intent. A fresh page recovers through its private `/my-prebid` lookup; it never needs another buyer's reference.

Buyer lot reads consume the explicit `/v2/auctions` projection, since strict v1 DTOs intentionally omit canonical mode/end-version. Only a missing v2 route permits the rolling-upgrade v1 fallback; outages are not hidden. Seller summaries share the policy panel's current mode. The owned `/auction-policy?listing_id=…` tab reuses the same buyer action/receipt implementation, so fresh-page recovery does not depend on a parent watch page keeping action slots mounted after reservation.

Policy and prebid facts are stored for destination `communications-auction-policy-v1`, deliberately **not enabled** by a relay until a compatible receiver is published. No private buyer ID, quote, reserve amount, cap or contact enters those event payloads.

## Reproduction

Export the project's pnpm shim PATH first. Heavy checks must run through `bt-heavy.sh`.

- Source-tree R0: `PYTHONPATH=packages/runtime/src python3 -m unittest discover -s tests/foundation -p test_extension.py -v`.
- Auction image and all current module migrations: `bt-heavy.sh python3 tests/lanes/L12/check-service.py`. Reuses the existing Auction test image with read-only current runtime/module/contract/test mounts, the shared PostgreSQL network and isolated databases/restricted roles; it never migrates a regular service database. Its named test container exits stopped and is not removed. If the reusable image is missing, build that one image separately through `bt-heavy.sh --build`.
- UI static: `bt-heavy.sh bash -c 'pnpm --dir web typecheck && pnpm --dir web lint && pnpm --dir web test'`. The new policy feature has its own discovered Vitest configuration.
- Production Compose + Chrome: create a local `.venv` from Python 3.11 and install Auction runtime/dev requirements plus websockets 15.0.1, then `bt-heavy.sh --build .venv/bin/python tests/lanes/L12/check-container-browser.py`. Builds only the changed web image, reuses the existing Auction image with read-only current source/contract mounts, runs both on an isolated proof database through the owned Compose fragment, and stops them without removing containers. Set `BT_L12_REUSE_WEB_IMAGE=1` and use ordinary `bt-heavy.sh` when web source is unchanged. Uses its own chrome-devtools session, loopback ports 3412–3414 after explicit port checks, actual 390px emulation and separate headless Chrome screenshot files. Every owned process is stopped in `finally`. `check-browser.py` alone is the faster host development variant.

Chrome proof uses real Auction handlers and isolated PostgreSQL operations against synthetic provider fixtures. It verifies public current-policy rendering and guarded/unavailable seller routes, EN/AR, light/dark, desktop/390px, one shell, no horizontal overflow, and phone-menu keyboard focus. It is not authenticated seller or connected Pricing/Orders/Identity acceptance. Money is not charged and physical receipt is not claimed.

## Local validation record

On 5 November, before the publishing window: source-tree R0 3/3 and fixed-path registry 3/3 passed; current Auction runtime image built and Auction Docker/module suite passed 45 tests with 4 scoped skips (three source-tree R0 checks and the opt-in fixture Chrome check run separately). Full web typecheck/lint passed and 342 web tests passed, with one separate opt-in connected-money skip. Production Auction/web started healthy through Compose. The earlier provider-fixture smoke passed 16 tab/locale/theme/device DOM cases plus 8 screenshots; the separate fully connected acceptance below repeated 16 authenticated cases and 8 authenticated screenshots. Actual inner width 390, one main shell, no horizontal overflow and phone-menu focus were asserted. All owned browsers, proof services and test containers are stopped. Evidence is ignored under `artifacts/l12-browser/`, `artifacts/l12-connected/` and scoped run logs; fixture smoke is not used as connected acceptance.

## Connected acceptance

`bt-heavy.sh --build .venv/bin/python tests/lanes/L12/connected.py` builds only the changed web image and reuses five existing domain images with current published source mounted read-only. Set `BT_L12_REUSE_WEB_IMAGE=1` and use ordinary `bt-heavy.sh` when the web image is current. Each image can be selected with `BT_L12_<SERVICE>_IMAGE`; missing images fail explicitly rather than triggering a fleet rebuild. Requires Python 3.11, the runtime/test requirements and websockets 15.0.1. The shared foundation PostgreSQL must already be running. Source copies from published Auction kernel v2, Pricing current v2, Orders commitment v2 and Auction close v1 are local-only and must never be committed here.

The script generates five isolated databases and distinct restricted owner/runtime roles, migrates only those databases, and starts real Identity, Catalog, Auction, Pricing, Orders and production web through Compose. It checks ports 3412–3414 before binding, uses unique project/container names on the shared network, creates explicitly synthetic accounts through actual registration/onboarding/review APIs and invokes Catalog's guarded, licensed sample importer. It never grants roles with SQL or seeds a winner, reservation, payment or physical inspection. Every service and browser it starts is stopped in `finally`; the isolated databases/roles are dropped and named stopped containers are retained.

On 5 November the real connected journey passed:

- Seller policy save and public reserve privacy; current seller-only authority and below-reserve configuration denial.
- Exact actor-owned authoritative prebid quote, explicit sample-fee review, one real awaiting-payment Orders reservation at USD 5,150. No money charged. A successful real HTTP reply was discarded once, then the same operation lookup recovered the receipt. Fresh-page private lookup and cross-buyer order denial passed.
- First bid versus reviewed Buy Now: only the prebid path won, canonical mode `prebid_reserved`, zero accepted bids and one succeeded reservation.
- An early private maximum published USD 4,000 without extending or meeting reserve. One late manual command produced two public manual/proxy rows at USD 4,200 but exactly one +120-second end/version change. At the actual extended deadline, the real close worker recorded `reserve_not_met`, no winner and no order. A private USD 6,000 cap never became public sale price.
- Sixteen authenticated seller/buyer locale/theme/device DOM cases, eight authenticated headless Chrome screenshots, actual 390px width, one main shell, no horizontal overflow and phone-menu focus recovery. Evidence: ignored `artifacts/l12-connected/`.

The private quote-validation seam binds durable admission revision R even after pending/reserved advances current revision to R+1/R+2. Wrong service/purpose/audience/buyer/quote and unknown legacy admission are tested. No guessed `current_revision-1` is accepted.

## Remaining integration boundaries

- Integrate the reviewed `push-events.js` through the one existing worker after its publication; no second service worker or cache/update-policy weakening.
- The receipt links to checkout with its retained `order_id`/`quote_id`. The checkout/payment UI is a separate provider surface; its browser-context handoff must be consumed when published. No payment-execution acceptance is claimed here.
- Repeat on main's final merged module set after provider merges; never commit local provider source copies.
