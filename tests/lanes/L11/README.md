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
BT_TEST_LANE=L11 python3 scripts/test-services.py service-operations
# With the Catalog runtime integrated:
BT_TEST_LANE=L11 python3 scripts/test-services.py catalog
pnpm --filter beirut-time-web typecheck
pnpm --filter beirut-time-web lint
pnpm --filter beirut-time-web test
pnpm --filter beirut-time-web build
```

PostgreSQL proofs require the foundation's local maintenance connection in `TEST_DATABASE_ADMIN_URL`. The foundation fixture creates unique disposable databases and restricted runtime/owner roles. Tests never reset ordinary domain data. They cover current official eligibility, coarse/fine capability boundaries, exact scoped permissions, cross-organization denial, private-owner reads, revision boundaries, concurrent writes, replay/conflicting keys, withdrawal/republication, exact currency units, Arabic/Persian reference digits, application/pool recreation, destination-isolated outbox claims and authenticated service-event issuer/audience bindings. Missing signing configuration leaves intent pending without claiming another module's events.

## Public browser proof

After a production build, `bash tests/lanes/L11/run-browser-proof.sh` starts loopback-only proof servers, imports labeled sample content through the real module commands, runs Chrome interactions and screenshots, and stops its own processes. The domain APIs and PostgreSQL persistence are real; **Identity onboarding/principal responses are an explicit V1 transport fixture in this proof**. It does not certify connected Identity onboarding or signed-in screen behavior. `L11_WEB_MODE=dev` selects the development server when diagnosing a foundation route.

The browser matrix asserts English/Arabic, light/dark, 1440×1000 desktop, actual 390×844 and 320×740 mobile emulation, and 932×430 landscape. It checks public selection context through locale links, current sample labels, control height, focused detail, absence of horizontal overflow, editable function separators and an uncovered final action. The gateway proof makes real same-origin private writes, restores their PostgreSQL results, checks replay/conflict and cross-owner isolation, and refuses a foreign mutation origin; its authority source remains the explicit Identity transport fixture, not a real login. Separate fault controls prove unverified businesses disappear, a movement outage cannot invent a compatibility/price result or take down the directory, and explicit retry restores canonical data.

`evidence/*-dom.json` contains measured results; `environment.json` identifies the proof mode. Screenshots use a separate headless Chrome with exact device metrics and the real preference cookie. This avoids the local screenshot-output defect and Chrome's minimum desktop-window width. No private credentials enter screenshots, query caches or browser storage.

The published two-file locale fix (`proxy.ts` and `next.config.ts`) is necessary for loopback production URLs. A successful `/api/health` alone does not detect the former redirect loop; the harness first requires a real localized HTML response with at most five redirects.

## Sample import and connected proof

The opt-in module fixtures only accept explicitly sample onboarded businesses and call authorized application operations. The directory fixture can add a sample brand plus an optional sample dealer. The movement fixture publishes a sample caliber with exact indicative USD minor units. Neither fixture creates a service appointment, received watch, accepted repair, inspection pass, paid order or payout.

The final connected proof must use current Identity onboarding and staff grants, a real buyer session, and the integrated Catalog runtime. Until that proof is recorded, fixture-backed public screenshots are not a substitute for connected acceptance. Physical-device installation, keyboards and assistive technology are separate from browser emulation.
