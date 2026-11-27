# Offers and assessed quote checks

## Scope and authority

Pricing owns offer agreement, exact sample fee/commission schedules, immutable
brand/repair quote versions, and explicit buyer decisions. Orders alone reserves
physical watches or records payments. Service Operations owns current technical
assessment/diagnosis; Catalog owns current listing/request facts. Missing peers
fail closed. No fixture transport or synthetic successful behavior is installed
in ordinary service runtime configuration.

The Auction runtime also supplies the shared canonical row lock, mode/end-version
CAS, first-bid intent/reconciliation and Catalog listing-edit fence. It does not
implement a second close or prebid engine. Those modules must use this kernel.

## Domain tests

Run from the repository root. The scripts reuse existing images with current
source/modules/contracts mounted read-only. They do not build images, add named
volumes, or read another service's SQL. Each run creates restricted, uniquely
named service-local databases against the shared local PostgreSQL and drops only
its own databases/roles at completion.

Set `BT_L14_PRICING_TEST_IMAGE` and `BT_L14_AUCTION_TEST_IMAGE` to existing
local test-stage image tags. Run connected, build and browser checks only on an
authorized proof host, not as part of the lightweight unit checks.

```sh
python3 tests/lanes/L14/run-existing-checks.py pricing auction
```

The images must supply the Python/runtime dependencies. The runner packages the
current registered domain contracts first. It includes the service's original
runtime/foundation/module tests as well as this directory's domain tests.

Coverage includes:

- Buyer/actual seller/current organization grants, wrong callers, self offers,
  blocked pairs, expiry, stale fees/source revisions and exact quote review.
- Stable actor/key/digest operations, lost allocation responses, simultaneous
  acceptance, competing Buy Now loss, leased recovery after browser/process loss.
- Assessed mandatory/optional lines, retained diagnosis and terms, selected exact
  totals, decline/expired held return, supersession and fresh attributable consent.
- Private retained financial history versus current authorization; retained
  balanced economics still read when a current source provider is unavailable.
- Canonical current Auction price, prebid admission-basis binding, closed-winner
  quote construction, strict close-command compatibility and private service JWTs.
- Bid/end-version atomicity, proxy-only private changes, exact legacy public event
  shape, first-bid unknown outcomes, global operation-key reservation, expired
  original bids reconciled without admitting a new bid, and leased recovery.
- Listing prepare-before-edit, frozen bidding, no-lot creation fence, immutable
  prepare/commit replay, exact source revisions/facts digest, Orders refence,
  and conservative rolling V1 fence handling.
- V3 edit prepare/dispatch lease CAS at exact expiry, dispatch-versus-expiry races,
  no speculative release after dispatch, independent exact Orders denial proofs,
  immutable confirmed aborts, V2 conservative recovery, and leased completion
  after a lost physical refence response; V2/V3 fixed-price no-lot edits finalize
  as pass-through without inventing an auction. Orders resolution consumes the
  exact published orders-commitment/v2.1 least-privilege read contract.

HTTP peers in these domain tests are explicit frozen contract fixtures. These
checks are not a claim of connected cross-service story acceptance.

## Actual Orders v2.1 provider transport

After copying the published Orders v2.1 preview into its owned paths (or merging
that provider), run:

```sh
python3 tests/lanes/L14/connected-edit-recovery.py
```

This reuses local Orders/Auction test-stage images, mounts current source and the
published foundation-extension/v2 module loader read-only, and creates two own
restricted databases. It starts only its own Orders Compose service on loopback
3633; the Auction app runs against its real restricted SQL database in an isolated
one-shot test process. Its bounded Orders client uses actual HTTP and service
JWTs. Catalog publication is an explicit frozen transport fixture in that test,
not a fake Catalog process or a publication/fee approval seeded into a real service.
No Identity grant, bid, edit result, denial receipt, order or payment is fabricated.
Only labeled unbid sample lot content is bootstrapped; physical commands/results
come from the actual Orders API. This is **not** a full Catalog or browser story
acceptance claim.

The check verifies the real stale-revision denial -> independent exact receipt ->
confirmed Auction abort/replay once, no bid, unchanged physical fence; producer
privacy and exact source matching; and missing/succeeded Orders receipts retaining
the dispatched Auction hold. `.local/edit-connected/evidence.json` records the
scope and non-secret outcomes. Own containers are stopped and only the run's own
databases/roles/secrets are cleaned, including migration-failure cleanup. No image
build, named volume, shared container change or generic operation-read widening.

## Q02 real marketplace proof

```sh
# No build: reuses four existing service images and current read-only source.
python3 tests/lanes/L14/q02-connected.py
# After a successful current web production build:
python3 tests/lanes/L14/q02-connected.py --browser
```

The no-build API check has passed against actual Identity/Catalog/Pricing/Orders
HTTP services with separate generated restricted databases. It registers labeled
sample actors through the native account commands, uses Identity's documented
one-time local operator bootstrap, then makes an independent actual private-seller
review. It uploads a generated safe sample illustration, creates/publishes two
explicitly labeled demo listings and reviews actual Pricing snapshots. No grant,
approval, published listing, financial review, offer result or reservation is
inserted as a fabricated terminal state.

Three concurrent commands (two seller-answered offers plus exact fixed Buy Now)
produce exactly one physical reservation. A separate positive accepted offer
produces its own exact 9270-minor awaiting-payment order with payment_authority
false. Self/expired/stale/blocked offers deny. No payment callback, watch release
or work execution is invoked. Non-secret evidence is in
`.local/q02-connected/api-evidence.json`; native login credentials are synthetic,
transient and never become financial browser storage. Own Compose services bind
loopback ports 3641..3644 and are stopped; own databases/roles/config are cleaned.

The authenticated browser phase passed through the real watch-detail offer slot,
then native account/offer controls: buyer preview/send, seller acceptance and the
buyer's canonical `/checkout/{id}` review at actual 390px. Sixteen form/accepted
observations and screenshots cover EN/AR, both themes and desktop/phone, including
sample labels and the current reserved-watch composition gate. Its own
`bt-s2-l14-q02` headless session uses loopback web3640/CDP19615 with same-page PNG
capture. It is separate from the already passed empty-state matrix below.

`--browser --guest-return` is an additional, strict guest sign-in return gate;
it has NOT passed yet. The shared Identity return-path allowlist currently omits
these new tabs. Its owner must publish the fix; L14 does not bypass the sanitizer
or fabricate a successful redirect. `browser-compose.json` explicitly records
`guest_return_checked:false` for the authenticated-only validation.

## Web tests and build

```sh
(cd web && pnpm typecheck && pnpm lint && pnpm test) &&
  web/node_modules/.bin/vitest run --config tests/lanes/L14/vitest.config.ts &&
  (cd web && pnpm build)
```

The lane Vitest config is rooted at the repository root, not `web/`. It checks
EN/AR parity, registration/gateway bounds, no browser financial persistence, and
exact BigInt selected-line fee rounding. Screens use the shared design system's
PageLayout/PageHeader/HeaderTabs/Card/SectionState/form controls and tokens.

## Actual empty/private browser matrix

After a successful production web build:

```sh
BT_L14_IDENTITY_IMAGE=beirut-time/accept-identity:local \
  python3 tests/lanes/L14/proof-shell.py
```

This reuses local Identity/Auction/Pricing runtime images; alternate image tags
can be selected with `BT_L14_{IDENTITY,AUCTION,PRICING}_IMAGE`. It checks loopback
ports 3610/3611/3613/3614 before starting its own `bt-l14-proof` stack. No unchanged
image rebuild is performed. The current source and contracts are read-only
binds. Unstarted peer origins deliberately point to a closed local port, not a
fake success server.

The native Account form registers fresh clearly labeled sample buyers in the
real Identity database, then exercises all three real private tabs: English and
Arabic, light and dark, desktop 1280px and actual emulated 390px. It asserts the
inner viewport width, RTL/theme, scoped empty response, tab shell geometry and
absence of horizontal overflow. All interaction is through the lane's own
`chrome-devtools-axi` session. Artifact capture uses `Page.captureScreenshot` on
that same authenticated headless Chrome target, avoiding a separate unsigned-in
screenshot process. The bridge, Chrome, web and own containers are stopped in
cleanup; only the run's own temporary databases/roles/config secrets are removed.

Ignored `.local/browser/` holds 24 JSON observations, HTML captures and PNGs.
`.local/shell-proof.json` records the scope: **empty/private real-service shell
only**, not populated offer/assessment/payment acceptance.

## Validation snapshot (2026-11-05)

- Pricing: 45 passed, including original runtime tests, the additive close
  adapter, malformed-provider fail-closed checks, typed private event payloads,
  normalized Service Operations URL configuration and startup-failure cleanup;
  Auction: 44 passed, including original runtime tests, 8 V3 edit-recovery cases
  and V2/V3 fixed-price no-lot regressions. One upstream Starlette/anyio
  deprecation warning per suite.
- Actual Orders v2.1 HTTP provider/restricted Auction component check passed;
  Catalog is explicitly fixture-scoped, not full connected story acceptance.
- Web: typecheck/lint passed; 304 existing checks and 7 lane checks passed. One
  existing opt-in connected-money test is skipped, not counted as proof.
- Current production web build and lint passed after the offer order-link,
  availability, sample-badge and accurate unavailable-state refinements. Real
  empty/private browser matrix: 24/24 passed; authenticated Q02 form/accepted
  matrix: 16/16 passed. Screenshots reviewed on desktop and 390px in both themes.
- Q02 actual API proof passed: positive offer acceptance, exact unpaid order,
  three-way reservation contention and self/expired/stale/blocked denials. Native
  phone preview/send/seller accept/buyer order review and watch-detail entry
  passed. Shared guest-return integration remains explicitly pending.
- No populated connected story acceptance claimed yet. Current assessment/service
  line adapters remain plan-matching fixtures until the provider freezes its
  published shape; Orders/L12/L13/L15 modules must be exercised together after
  their source handoffs. New event destinations remain held until subscribed
  authenticated receiver contracts are supplied. Retained reads never authorize
  allocation/payment/work, and no payment/work result is fabricated.

## Park handoff

Saved independently of the remaining provider integrations. Runtime checks used
published `foundation-extension/v2`, `catalog-requests/v2` and
`orders-commitment/v2.1` previews where those changes were not yet on main. These
borrowed files are deliberately NOT part of this branch; use merged main or the
published copies for checks after resume, never commit a neighbor's files.

Remaining acceptance work: align brand/repair current-source adapters to the L17
assessment/service-line freeze and actual diagnosed-case authority; subscribe new
outbox destinations through the L22 receiver contract; and consume L19's shared
Identity return-path fix before passing `--guest-return`. No populated C09/S02 or
guest-return acceptance is claimed. Authenticated Q02 native controls, real
reservation contention, current production build and 16 localized/theme/viewport
observations have passed. No payment or execution was invoked.

## Source ownership

Commit only L14-owned roots. Foundation-extension copies used for local
registration/builds are borrowed and must not enter a lane commit. Module IDs
`L14.a-kernel` and `L14.a-current` carry additive migrations after immutable L05
and L07 ledgers. Do not append/rename historical migrations or stage generated
registry indexes, local screenshots, credentials or borrowed provider sources.
