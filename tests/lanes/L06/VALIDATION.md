# L06 validation

## Scope

Private maximum is a pure `auction.proxy.v1` hook inside Auction's sole admission
transaction, plus its registered maximum route. Auction owns permissions,
idempotency, database locking, persistence and durable outbox delivery. Buyer
workspace is a stateless, owner-authorized composition of Auction and Orders;
it does not create a second activity database or fabricate payment/winner state.
Neither module needs an artificial migration or separate outbox.

## Checked on 2026-11-04

- Initial foundation copied with `rsync -a --exclude=.git`, dependencies installed
  frozen, production build and health check passed before domain changes.
- Current main (foundation, Identity, Auction, discovery, Verification, Orders and
  Brand options) merged normally without conflicts. Borrowed overlapping files
  were compared with main and only verified untracked copies removed. Older
  foundation copies were first refreshed to main. No foundation changes are
  contributed by this lane. Pricing's published quote contract remains an
  uncommitted dependency until its owning merge.
- Owned Python suite: **64 passed**, including real ASGI/JWT boundary checks.
  Ruff passes for both modules and owned tests. Missing/expired/wrong-purpose
  tokens, fresh Identity subject/session/role mismatch, represented-business
  context and 401/403, cross-owner
  projection rows and malformed success responses fail closed. Dependency
  failures return unavailable, never fake empty activity.
- Docker module proofs passed using the existing proof image (latest
  Communications module suite: **45 passed**). Latest
  Communications proof mounted main's current runtime read-only. Containers are
  retained stopped; no new images or shared-cache pruning under the disk rule.
- **72 actual Auction SQL regression tests passed**, including 9 proxy
  integration cases, against restricted disposable databases using the existing
  Auction test image and main's mounted runtime. The registered L06 maximum
  route persisted a 450000 cap and responded at
  430000 to a 420000 manual bid. Other tests cover earliest equal caps, cap-bounded
  partial increments, leading-cap raises without price transitions, missing hooks,
  non-increasing caps, and no private cap in history/outbox. The owner suite's
  pure hook fixture is byte-identical to the installed L06 hook; the registered
  route case explicitly loads L06. Other-domain dependencies in this SQL suite
  are versioned transport fixtures, not a full live marketplace proof.
- Owned web suite: **70 passed, 1 opt-in connected test skipped**. Covers exact
  Arabic/Persian digit parsing, safe money bounds, private cache partitions,
  signed-out/restoring/unavailable states, role denial, cancellation on account
  switch, retained uncertain command keys/body, reviewed fee snapshots and
  EN/AR activity. Every private request is explicitly bound to Identity's
  access fingerprint; financial data and actions hide unless authenticated.
- Main foundation web suite: **66 passed**. Current production build and
  TypeScript check pass. Owned-path ESLint passes. Full-web lint currently fails
  in main's `web/features/brand-options/view.tsx` with three
  `react-hooks/set-state-in-effect` errors; reported to the integration owner.
- Opt-in connected Pricing test passed against actual Identity/Pricing APIs and
  databases: two labeled sample buyers, retained owner quote and review,
  other-buyer denial, bid quote denied purchase-only reservation authority, and
  session logout. The proposed subject was explicitly NOT an existing Auction;
  this proves private non-binding fee preview only. Repeated successfully after
  the final access-fingerprint binding change using isolated real Identity and
  Pricing runtimes, existing images and restricted disposable databases.
  Owner review, other-buyer denial and purchase-only rejection passed again.
  Owned runtimes stopped and test databases were released; no shared service or
  ordinary domain database was altered.
- Chrome production checks covered both `/buyer` and
  `/buyer/auctions/[listingId]`, EN/AR, light/dark, desktop 1440x900/DPR1 and
  phone **actual 390x844/DPR3**, sixteen boundary cases. Phone emulation used
  `emulate --viewport 390x844x3,mobile,touch`; `resize 390` was rejected because
  Mac Chrome clamped it to 500px. Checked actual viewport, language/direction,
  theme, no horizontal/heading clipping and minimum 44px action targets.
  A separate clipped CLI screenshot is not accepted as phone evidence.
- Same-origin browser maximum POST reached the real 401 boundary, not an Origin
  denial; foreign Origin was denied. Explicit local BFF origins and forwarded
  origin trust off were used. Arabic unavailable-Auction retry was exercised.
  These checks do not acknowledge a bid or show invented activity.

## Remaining connected acceptance

- Latest session-state changes passed another sixteen production Chrome
  boundary cases with actual 390px phone emulation, EN/AR and both themes.
  Identity was unavailable: explicit retry rendered, with no cached private data.
- Real two-buyer browser competition, fresh fee review, server admission,
  public-safe stream/outbid delivery, restart/concurrency and stale/self/late
  rejection must be checked together with all source services. SQL admission
  proofs above are not a replacement for the full connected demo.
- Exercise actual `/v1/my-bids` and `/v1/me/reservations` responses together with
  Communications and follow `/checkout/<id>` for a real, unexpired
  awaiting-payment reservation. Current main's order-detail route and projection
  confirm this ID binding; the obsolete ignored query parameter was removed. Auction lifecycle and buyer status
  remain distinct; ended participation is not a winner. Missing provenance is
  not silently labeled production content.
- No final-results, payment or delivery action is fabricated. Sample fee policy
  is explicitly labeled, never represented as approved commercial tariffs.

Browser snapshots, borrowed-file audits and temporary logs are ignored local
artifacts, not production fallback responses. No ordinary domain database was
modified for the disposable SQL proofs. Connected fee-preview checks added only
explicit sample buyer/quote records through real APIs.
