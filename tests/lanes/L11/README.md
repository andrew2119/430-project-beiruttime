# Official care proof

## Scope

- Service Operations owns published directory profiles and buyer-private choices.
- Catalog owns identified brand movement options and buyer-private movement selections.
- Every business read rechecks Identity Businesses V1 over a bounded dependency. Active onboarding, authenticated-business assurance, matching organization and current coarse capabilities are mandatory.
- Service profile writes require the selected organization's `business.jobs.write`; movement publication requires `business.stock.write` on an eligible brand. No platform role overrides another organization's scope.
- Selections are revision-bound, idempotent PostgreSQL commands with atomic outbox intent. Unsupported configurations are saved for manual review, never a physical feasibility pass or a guaranteed price.

## Automated proofs

```sh
.venv/bin/python -m pytest tests/lanes/L11 -q
node --test tests/lanes/L11/format-money.test.mjs
# Reuse the current service-operations runtime image; migrate only a disposable database:
.venv/bin/python tests/lanes/L11/runtime-compose-proof.py
BT_TEST_LANE=L11 python3 scripts/test-services.py service-operations
# With the Catalog runtime integrated:
BT_TEST_LANE=L11 python3 scripts/test-services.py catalog
pnpm --filter beirut-time-web typecheck
pnpm --filter beirut-time-web lint
pnpm --filter beirut-time-web test
pnpm --filter beirut-time-web build
```

PostgreSQL proofs require the foundation's local maintenance connection in `TEST_DATABASE_ADMIN_URL`. The foundation fixture creates unique disposable databases and restricted runtime/owner roles. Tests never reset ordinary domain data. They cover current official eligibility, coarse/fine capability boundaries, exact scoped permissions, cross-organization denial, private-owner reads, revision boundaries, concurrent writes, replay/conflicting keys, withdrawal/republication, exact currency units, Arabic/Persian reference digits, application/pool recreation, destination-isolated outbox claims and authenticated service-event issuer/audience bindings. Missing signing configuration leaves intent pending without claiming another module's events. Filtered directory scans verify at most the requested page size and preserve a progress cursor even when all first-page rows are excluded. A withdrawn movement retains its private snapshot across application/pool recreation. Both domain adapters distinguish Identity 401 (refresh/sign-in), 403 (scope denied), and malformed/unavailable responses (503), without committing a write or outbox event.

## Public browser proof

After a production build, `bash tests/lanes/L11/run-browser-proof.sh` starts loopback-only proof servers, imports labeled sample content through the real module commands, runs Chrome interactions and screenshots, and stops its own processes. The domain APIs and PostgreSQL persistence are real; **Identity onboarding/principal responses are an explicit V1 transport fixture in this proof**. It does not certify connected Identity onboarding or signed-in screen behavior. `L11_WEB_MODE=dev` selects the development server when diagnosing a foundation route.

The browser matrix asserts English/Arabic, light/dark, 1440×1000 desktop, actual 390×844 and 320×740 mobile emulation, and 932×430 landscape. It checks public selection context through locale links, current sample labels, control height, focused detail, absence of horizontal overflow, editable function separators and an uncovered final action. The gateway proof makes real same-origin private writes, restores their PostgreSQL results, checks replay/conflict and cross-owner isolation, and refuses a foreign mutation origin; its authority source remains the explicit Identity transport fixture, not a real login. Separate fault controls prove unverified businesses disappear, a movement outage cannot invent a compatibility/price result or take down the directory, and explicit retry restores canonical data.

`evidence/*-dom.json` contains measured results; `environment.json` identifies the proof mode. Screenshots use a separate headless Chrome with exact device metrics and the real preference cookie. This avoids the local screenshot-output defect and Chrome's minimum desktop-window width. No private credentials enter screenshots, query caches or browser storage.

The published two-file locale fix (`proxy.ts` and `next.config.ts`) is necessary for loopback production URLs. A successful `/api/health` alone does not detect the former redirect loop; the harness first requires a real localized HTML response with at most five redirects.

## Real buyer session and UI proof

With the published Accounts module and Identity-local runtime helper staged in their owning paths, run:

```sh
L11_REAL_ACCOUNTS_PROOF=1 bash tests/lanes/L11/run-browser-proof.sh
```

This mode adds a third isolated PostgreSQL database and uses the published real Accounts registration, signed access tokens, HttpOnly refresh-cookie rotation and live principal routes. Registration through its API is a test precondition; this lane does not own or certify the account page. Business onboarding and authorized brand staff remain explicitly labeled V1 fixtures. The published dispatcher is absent from the route handoff, so only a temporary metadata copy disables that worker; no account-message delivery is claimed.

`buyer-{desktop,phone}-dom.json` records actual buyer UI service/movement saves, reload and locale/theme restoration, exact edited requirements, private original USD quote snapshots after the public option changes to explicit LBP minor units, stale-revision explanation, reachable actions, cross-buyer isolation and private-state clearing when an actual revoked session is discovered by a private action. Each runs in EN/AR and light/dark at 1440px and actual 390px. No access token is injected into the UI or persisted in browser storage. Private queries and commands pass their render owner's access fingerprint to the current published session wrapper, which rejects stale ownership before admission and fences late answers. Browser editing uses focus, native text selection and trusted keyboard input: this local browser adapter's CSS `fill` updates the DOM without React state, and CSS `click` alone does not focus a text input.

## Sample import and connected proof

The opt-in module fixtures only accept explicitly sample onboarded businesses and call authorized application operations. The directory fixture can add a sample brand plus an optional sample dealer. The movement fixture publishes a sample caliber with exact indicative USD minor units. Neither fixture creates a service appointment, received watch, accepted repair, inspection pass, paid order or payout.

LBP values are displayed explicitly as raw integer minor units until an explicit versioned pricing exponent is available; the screen never guesses a whole-lira/cents conversion. USD uses its defined cents representation. Saved snapshots retain their original currency, minor value and configuration even when an option changes or is withdrawn.

The final connected proof must use current Identity onboarding and staff grants, a real buyer session, the integrated Catalog runtime, and a versioned Communications acknowledgement for the four care event types. The published Auction-only `/internal/v1/events` receiver does not accept Service Operations/Catalog intent; delivery remains pending until the generic receiver seam is frozen. Until that proof is recorded, fixture-backed public screenshots are not a substitute for connected acceptance. Physical-device installation, keyboards and assistive technology are separate from browser emulation.
