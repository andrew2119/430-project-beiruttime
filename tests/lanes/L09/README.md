# Moderation, operations and technical intake

## Delivered surfaces

- Trust: private listing/user/message reports; independent claim and separately authorized, audited assignment recovery; reasoned warn/hide/suspend/reinstate/dismiss decisions; correction/appeal; revision-bound idempotency; append-only audit history and durable delivery state. Duplicate, report-velocity and reported-payment-abuse rules produce human-review flags, never automatic penalties or a social score.
- Communications: current role-scoped verification/moderation projections; separately authorized inspection/dispute/quality routes with explicit awaiting-prerequisite states and no invented results. Projection previews omit evidence and identity documents.
- Service Operations: private business-scoped intake, serial/reference/movement, condition/accessories, reported/assessed issues and explicit acknowledgements. Private condition photos/prior-owner records are bounded, organization-scoped downloads, never public previews. No receipt means awaiting intake. Matching actual Orders custody plus all acknowledgements is required for diagnostic-opening readiness; detail reads revalidate the current receipt, so a fenced or unavailable receipt cannot keep authorizing diagnostics. Intake never records an authentication, repair or quality pass.
- Web: `/operations/moderation`, `/operations/dashboard`, `/operations/dashboard/queues/{key}`, `/business-intake`; English/Arabic, RTL, semantic light/dark surfaces and the common phone breakpoint. Current Identity session coordination is reused with the view-owner `accessFingerprint` admission fence and abort-on-unmount command signals; no credential enters a URL, persisted draft or query key. Cached private previews are suppressed during fresh scope checks or errors and dropped after unmount. Only public listing choices, currency preference and scoped record/business selections survive locale navigation; private evidence, serials, notes and financial amounts never enter browser storage.

## Checks

```sh
export PATH=/Users/andrew/.harness/homes/430-project/firstmate/data/bt-tools/bin:$PATH
# Reuse a previously validated dependency image when available:
# BT_L09_TEST_IMAGE=<existing-image> python3 tests/lanes/L09/check.py
python3 tests/lanes/L09/check.py
pnpm --filter beirut-time-web typecheck
pnpm --filter beirut-time-web exec vitest run --config ../tests/lanes/L09/web/vitest.config.ts
pnpm build
cd web
pnpm exec eslint features/moderation 'app/(moderation)' 'app/(operator)' 'app/(intake)' registrations/L09.ts
```

The Python runner builds only the Trust dependency test image when `BT_L09_TEST_IMAGE` is unset. Set that variable to a previously built image to avoid rebuilding; current module, test, shared-runtime and registered-contract sources are mounted read-only, so a reused dependency image cannot silently test old source. Each service's own module tree joins the common test harness. Finished foreground containers remain stopped; shared images, cache and storage are never pruned. Every database proof uses unique disposable databases and restricted owner/runtime roles; ordinary domain schemas are never migrated by this runner. It also runs the common service, outbox, inbox, ledger and cross-database isolation proofs. Provider transports in these tests are explicit V1 fixtures, not production fallbacks.

After copying the published Directory V1 module into its provider-owned paths (uncommitted), run `BT_L09_INTEGRATION_ONLY=directory BT_L09_TEST_IMAGE=<existing-image> python3 tests/lanes/L09/check.py`. This explicitly composes the real Directory and Intake modules in one Service Operations database. Actual directory publication is required; later official-business revocation or loss of servicing capability prevents private intake access. Only the Identity transport is a fixture in this proof; it cannot establish final current-account authority.

Before publishing committed work, run `python3 tests/lanes/L09/check-ownership.py`; it rejects any committed path outside this lane or a renamed branch. Keep `bt/bt-l09` and put the real feature reference in the review title. Temporary provider/foundation copies must never be staged.

A browser matrix is available as `bash tests/lanes/L09/browser-matrix.sh`; it uses a private browser session and never injects tokens or grants authority. `BT_BROWSER_BASE` selects the running web origin. Sign in through Identity for the authorized scenario, and also exercise a signed-out and ordinary-buyer scenario. Screenshots/evidence are local under ignored `artifacts/l09/`.

## Isolated signed-in browser proof

Use a previously validated dependency image; this harness never builds one:

```sh
BT_L09_TEST_IMAGE=<existing-image> python3 tests/lanes/L09/browser-proof.py start
# Open the printed fixture-login URL with your own chrome-devtools-axi session.
# Select an explicitly labeled sample profile and sign in through the session API.
# When finished:
python3 tests/lanes/L09/browser-proof.py stop
```

The harness serves the actual three domain modules against separate disposable databases and restricted roles, alongside clearly labeled V1 dependency transports. It temporarily installs a fixture login page and Identity gateway entries, using the shared session coordinator and real HTTP login rather than injecting a principal. The public fixture-only password appears on that page; it is not a marketplace credential. No custody receipt or technical pass exists in this proof. Sample profiles include buyer, independent reviewer, operator, technical business and unrelated business. When the published Directory module is present, the harness publishes labeled sample servicing profiles through its actual command API and routes Intake eligibility to that real module; otherwise only the explicitly fixture-labeled Directory transport is exercised. On the fixture portal, `window.__l09FixtureSignIn(email)` calls the same login API and returns only success; it survives client navigation for testing account-switch purges without a page reload.

Exercise report/claim/decision, private intake/evidence upload/download, revision conflict/refresh and same-page business-switch denial. The ordinary browser matrix can then check signed-in screens with `BT_BROWSER_ROUTES` selecting routes and preserved query strings. Always stop the browser and harness: stopping restores the product registration, removes the temporary product page, closes the proof databases/roles and stops only its own containers. The ownership check refuses a committed fixture overlay. These tests prove domain behavior against contract fixtures, **not** final connected acceptance.

## Connected acceptance

The owning provider implementations must be connected before calling the full demo accepted:

1. Catalog listing lookup and authenticated `trust.moderation.decided.v1` consumer must hide/reinstate visibility while leaving allocations, custody, payment and dispute duties untouched. A saved Trust decision remains visibly pending until destination acknowledgement.
2. Identity account report-subject lookup, current principal/grants, and current private-review queue must match the published versioned contracts. A missing/denied provider never fabricates a report subject or queue record.
3. The official-directory lookup must confirm the selected brand/dealer; Orders must provide an actual matching immutable custody receipt before a record becomes received. Missing receipt support is unavailable, not fabricated custody.
4. Signed-in desktop/phone flows must be checked in both languages/themes against those real connected providers. Fixture transport proofs alone do not establish this acceptance.

The provider seams and Python/TypeScript schemas live in `packages/contracts-trust/moderation/` and `packages/contracts-service/intake/`.

## Sample entrypoints

Module fixtures are explicit opt-in application calls, not startup database seeds. The Trust fixture files a labeled sample report against an existing sample listing. The intake fixture creates only a labeled preparatory record for a supplied order/business, with no receipt, permission or technical pass. A current authorized principal is required for either call. No fixture creates custody, a winning bid, a paid order, an inspection pass or completed work.
