# Shared interface verification

## Foundation and scope

The foundation uses local Lexend Deca files, four-tier tokens, Light/Dark palettes, shared controls, Calm headers, Pane tabs, sticky condensation, motion, sidebar/profile footer and mobile shell. All page areas now consume that foundation. The root is a dashboard; Settings is a real profile/account, language and appearance screen.

[The design contract](design-system.md) records shared stylesheet, component and motion ownership.

At a 1280×900 viewport, Settings measured rail x16/y16, 224×868; tray x254/y16, 1010×868; header x282/y40, 954×132. At actual 390px phone width, the tray measured x8/y64, 374×712. Settings does not expose nonexistent profile-photo, timezone, chat or notification APIs. The desktop rail has no manual-collapse control. Arabic uses logical-property adapters and local Noto Sans Arabic glyph coverage.

## Automated checks

Passed on the final integrated source:

- Web typecheck and lint.
- **302 root/feature tests passed; one opt-in connected-money test skipped.** The default web test command now runs every feature-owned Vitest configuration as well as the root tests.
- **22 supplementary lane tests passed:** L07 (3), L08 (10), L09 (9).
- Shared UI lint: no errors; one native-image optimization advisory. ImageFrame deliberately retains caller-owned marketplace URL/media policy rather than introducing a new image proxy.
- Production build and whitespace/diff checks.

No service runtime or Docker configuration changed.

```sh
pnpm --dir web typecheck
pnpm --dir web lint
pnpm --dir web test
web/node_modules/.bin/eslint packages/ui/src --config web/eslint.config.mjs
web/node_modules/.bin/vitest run --config tests/lanes/L07/vitest.config.ts
web/node_modules/.bin/vitest run --config tests/lanes/L08/web/vitest.config.ts
web/node_modules/.bin/vitest run --config tests/lanes/L09/web/vitest.config.ts
pnpm --dir web build
git diff --check
```

## Real-browser checks

An isolated Chrome session, driven through chrome-devtools-axi, checked English and Arabic, Light and Dark, 1280/1440px desktop and **asserted `innerWidth === 390`** phone emulation (390×844, DPR 3, mobile/touch).

- **264 baseline cases:** 33 route shapes × two languages × two themes × desktop/phone. Covers dashboard, Settings, public discovery/detail/search, account/consent, seller listing/edit/auction/verification, private buying/checkout/inbox, customization/services, business and operations routes. Unavailable dependencies and signed-out boundaries remain truthful, navigable states.
- **128 populated cases:** seven buyer-area and nine business/operator pages × the same language/theme/viewport combinations. Checks include overflow, visible content fit, keyboard focus, selected tabs, shared header geometry, phone text fields ≥16px and applicable enabled phone targets ≥44px.
- **12 persisted shell regressions:** one-column phone dashboard cards, Escape focus restoration for both drawer doors, navigation focus handoff, asynchronous theme-radio keyboard focus/cookie retention, and language route/direction changes in both languages. Reproduction lives in `web/scripts/design-browser.js`.
- **20 role/locale/viewport probes:** buyer, private seller, dealer, brand and operator. Every sidebar/drawer destination exactly matched the existing registration's public-or-role permission filter. Guest/unavailable-session browsing was included in baseline checks. These are presentation probes, not backend authorization proofs.
- Buyer interactions passed in both languages: keyboard currency switching/focus return, retained quote review, draft save/edit, unreleased-control disabling, preference switch keyboard behavior, inbox read/exit/navigation, maximum preview/acknowledgement, reservation acknowledgement and restricted intake/hold wiring.
- Business interactions passed on desktop and phone in both languages: native FormData/reset synchronization, contact verification, Arabic digit normalization, moderation/intake controls and draft locale recovery without persisting private fields.
- Menu reveal measured 200ms; runtime theme changes called the actual View Transition API with the shared 450ms duration. Input focus rings and Escape focus return were verified. Populated buyer/business phone pages had no console errors.

The integration review caught and repaired missing home phone-layout scoping, drawer invoker restoration and theme-radio focus racing the asynchronous View Transition update. Regression coverage remains in the repository.

All populated API data was explicitly synthetic and loopback-only, flowing through the real web/BFF/client path. No fixture import, auth bypass, fake saved preference API, or test route is present in the production application. These checks do not establish real payment, settlement, custody, auction outcomes or production-service availability. No physical-device installation or hardware-keyboard phone test is claimed.

For shell-only reproduction, start your own loopback app at the origin in `web/scripts/design-browser.js`, then:

```sh
export CHROME_DEVTOOLS_AXI_SESSION=bt-design-check
chrome-devtools-axi open http://127.0.0.1:3247/en
chrome-devtools-axi emulate --viewport 390x844x3,mobile,touch
chrome-devtools-axi run < web/scripts/design-browser.js
chrome-devtools-axi stop
```

Assert the returned `passed` value. Area mapping/validation documents contain their populated fixture reproduction steps. All verification browser sessions and proof servers were stopped after use.

## Screenshot evidence

The historical screenshot matrix includes:

- `before-en-desktop.png`: actual original interface.
- `after-{dashboard,settings,prices,account,seller,business,operator}-{en,ar}-{light,dark}-{desktop,phone}.png`: 56 final captures. Seller/account captures intentionally show real unavailable boundaries; buyer/business/operator captures use the labeled synthetic transports above.
- `after-drawer-ar-dark-phone.png`: mirrored Arabic drawer and profile footer.
- `checks/`: final route, populated, role, focus and geometry records plus automated results.

Phone captures use actual device emulation and headless Page.captureScreenshot. A plain 390px headless window was found to lay out at 500px and crop; the historical `before-en-cropped500.png` is retained only as a labeled crop, **not** as 390px evidence. The CLI screenshot writer could report success without writing a file, so saved PNGs were checked directly.

### Public shell and preference composition

The root composes the canonical shell for every route. Home, About and Settings
use its page frame, header, controls and first-answer arrival. Their additive
contracts live in `web/shell/foundation/pages.json`. The frozen page ledger keeps
its original hashes; only a registered rebuild with its declared view and shared
composition replaces a frozen page check. Unrelated frozen pages and shell files
remain immutable.

Language controls update the shared locale context in place. These three views
resolve copy and destinations from that context. The mounted child subtree is
never keyed by language. Query strings, fragments, passwords, private file inputs
and pending operation references remain in memory. Only language and appearance
preferences are durable. Access changes invalidate the shared memory read scope.

| Route | Data/read key | Warming | Retained answer and first frame |
| --- | --- | --- | --- |
| `/` | Static navigation filtered by current access; no market read | Shared full-route intent and visible-link warming | Current access labels; one arrival per access scope |
| `/about` | Static bilingual copy; no remote read | Shared full-route intent and visible-link warming | Copy is present immediately; one arrival per access scope |
| `/settings` | Existing identity subscription; no new remote read | Shared full-route intent and visible-link warming | Identity restoration alone uses a skeleton; preference sections stay mounted |
| `/internal/page` | Existing demo definition, mode and page | Shared route and data intent engine | Existing retained-answer, refresh-content and first-load placeholder rules |

These are implementation contracts, not measured speed or connected acceptance.
The canonical shell mounts the existing shared warming controller once.
The owned path dependency composes public page contracts into the registry input
before the shared registry takes its immutable snapshot. The frozen internal
source table is unchanged. Home, About and Settings have explicit no-read policies: static copy
and navigation need no remote answer, and Settings observes the existing identity
subscription. The controller shares the existing memory scope, read definitions,
refresh policy and running signal. There is no additional controller. Unknown routes retain native full-page prefetch; registration
never grants permission or dispatches a command.

The six methods apply through full-route readiness requests, data on intent for
registered reads, access-scoped retained answers, content during refresh,
first-load-only placeholders and one answer arrival. Static pages have no loading
answer to retain or refresh. The internal read fixture exercises those data
branches using the same definition for warming and mounting. Domain owners still
must publish their actual read definitions before claiming their data adoption;
no fixture asserts a connected market answer.
Language changes merge a fresh server route response into the mounted client
tree so server copy, recovery destinations and slot locale props update too.
The header uses a preference button, outside legacy navigation interception,
and never saves a draft or retries a pending reservation. Other domain page
rebuilds remain with their page owners. The canonical shell alone does not certify
their six speed methods or their language retention.

The existing public-only worker has one registration in the canonical shell.
Updates require an explicit reload action; language changes never reload. Push
dispatch integration remains owed to its producer. No private data is added to
worker caches.

Separate-machine proof remains owed for emitted page sizes, network readiness,
actual mounted password/file retention through both controls, screenshots in both
languages and themes, keyboard flow, safe-area/target geometry and the viewport
assertion `window.innerWidth === 390` at 390 by 844. A physical phone remains
required for a complete phone-feel claim. No production build or connected
transaction is established by the focused module checks.

The canonical page header uses the shared raised-card rows, sticky measurement,
title fitting and width-driven phone stylesheet. Settings uses the shared pane
tabs with a measured single-line ruler and tile fallback, alongside its wide
section index. Home and About use the same header boundary. These structural
checks do not establish browser geometry or physical-phone acceptance.

The preserved language interface keeps both change-hook names and the dedicated
legacy-link capture before document-level draft handlers. Compatibility shell,
profile, preference, provider and focus entries now delegate to their shared
compositions. Their frozen ledger hashes remain unchanged. The contract check
requires each rebuilt entry to render its declared shared view, and the shell
view to render the single boundary. Other frozen entries still require exact
bytes. The retired shell styling debt is absent from its rebuilt entry.

The scheduling and registration suites use deterministic local contract fixtures
because their route implementation and widened runtime validator are outside this
snapshot's owned boundary. Scheduling examples cover civil-time review, exact
confirmation and retained action references; registration examples cover lane
and version boundaries. Passing these fixtures does not prove runtime dispatch,
timezone interpretation or generated-registry integration. Those connected checks
remain owed against the implementations before acceptance.
