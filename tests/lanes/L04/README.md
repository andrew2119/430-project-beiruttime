# Discovery and live projection validation

## Implemented surfaces

- Public `/watches`, `/search`, `/watches/{id}` and canonical `GET /v1/listings/{id}`.
- Responsive EN/AR, RTL and light/dark, Arabic aliases/digits, exact minor-unit filtering, null-price offers, stable filter-bound cursors and reproducible URLs.
- Frozen Catalog public-view mapping; current Orders stock and matching physical-watch/mode/provenance bindings; current Identity business assurance. Publication registration is never used as current availability.
- Actual Auction timing feed controls ending-soon order. Core snapshot/history controls masked bids, monotonic server-clock countdown and revision-bound end state. No parallel bid engine or invented extension/winner/payment.
- Actual public-photo paths, decoded gallery/zoom, complete public credit/license/change text, condition/wear/included items and modified-part provenance/warranty disclosure. No private evidence URL is projected.
- Optional sale controls load only after a current public/available listing read. Access changes remount controls; each contributing domain retains command authorization.

## Recorded checks — 2026-11-04

- Docker/Python 3.11 + isolated PostgreSQL: **37 passed** (16 Discovery proofs and 21 common proofs). Databases and restricted roles are disposable; ordinary domain databases are never migrated/reset by these proofs.
- TypeScript, ESLint and production Next build: **passed**. Frontend units: **nine L04 tests** and **58 common web tests passed**.
- Production-web Chrome contract fixture: **16 browse/detail cases passed** at asserted **1440×900 / 390×844**, EN/AR and light/dark. Device metrics and internal clipping are checked; Mac window resizing alone silently clamps to 500px and is not phone proof.
- Six additional bilingual disclosure cases and maximum-price detail at actual widths 320/850/851 passed. Gallery Escape/focus return, Arabic numeric input, truthful empty/range/private-reference states and canonical ending-feed filtering passed.
- Current-stock outage preserves public detail but disables sale authority. Revoked or sales-ineligible businesses cannot become command publication proof; canonical UUID references normalize before Auction lookup. Timing validates before/equal/after boundaries and cannot simulate an ordinary-auction extension. Missing attribution suppresses uncredited photos. Unstated offer prices stay null; unopened auctions remain explicit. Failed photo loads show unavailable, retry at most twice with jitter and recover without claiming no photograph exists.
- Two independent Chrome viewers observed a **contract fixture** canonical update in **657ms / 300ms**. Six-sequence gap recovery, wrong client wall clock, stale-price suppression and reconnect/fresh-time recovery passed. Transport fixtures use a one-second breaker cooldown to keep recovery tests bounded; this is not a real-service SLA measurement.
- A separate actual 390×844 reduced-motion proof confirms `animation-name: none` while status announcements remain present. Evidence: `browser-evidence.json`, `motion-evidence.json`.

The browser fixture uses the frozen real public-view and HTTP DTO contracts, a disposable PostgreSQL database, synthetic gallery cards and explicit transport fixtures. **It is not evidence of actual stock publication, real bid admission, independent inspection, payment or the final connected-service demo.** Physical phone installation/keyboard/assistive-technology acceptance is not claimed.

## Reproduce

With the integrated Catalog runtime present:

```sh
export PATH=/Users/andrew/.harness/homes/430-project/firstmate/data/bt-tools/bin:$PATH
BT_TEST_LANE=L04 python3 scripts/test-services.py catalog
pnpm --filter beirut-time-web typecheck
pnpm --filter beirut-time-web lint
pnpm --filter beirut-time-web test
pnpm --filter beirut-time-web exec vitest run --config ../tests/lanes/L04/vitest.config.mts
pnpm build
```

The Discovery test module scopes its own provider-contract database to Discovery migrations, without shadowing common/runtime fixtures. Browser fixture entry points also explicitly load only this module and cannot become a second authoritative Catalog runtime.

`browser_matrix.py` and `browser_reduced_motion.py` require the opt-in fixture on loopback 8144 and a production web build on 3044 with `CATALOG_API_URL=http://127.0.0.1:8144`, `BT_PUBLIC_WEB_ORIGINS=http://localhost:3044,http://127.0.0.1:3044` and forwarded-origin trust off. They use isolated `chrome-devtools-axi` sessions. Fixture control routes are never loaded by the production module. Stop completed containers and browser sessions; preserve the shared PostgreSQL process. Reuse existing test images with read-only source/test/contract-fixture mounts when appropriate; do not rebuild everything or prune shared storage.

## Connected integration gates still open

1. Run against actual Catalog publication/media, Orders availability, Identity businesses and Auction timing/history services, with all owning modules present. The schema/DTO adapters are implemented; connected acceptance must not substitute the isolated transport fixtures.
2. Publish the attributed sample stock through real authorized operations, place actual accepted bids and compose the contributing bid/proxy/sale slots. Repeat desktop/phone EN/AR/theme and two-viewer/reconnect checks with those real services. Never seed a winning bid, paid order or independent pass.
3. After foundation reaches main, verify copied foundation files byte-for-byte, remove only identical untracked copies, merge main without rebasing and rerun checks. Temporary copied runtime/provider files and published foundation patches are not L04 deliverables.
