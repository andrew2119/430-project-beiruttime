# Buyer-area Creator Pipeline port — validation and integration report

Branch: `bt/bt-cp-buyer` (local only). Shared foundation: published `foundation-v3.tar.gz`; no foundation files belong to this area's commits. The area branch is rebased onto current local `main` before delivery. `bt/cp-design` still pointed to the original base while its frozen archives were being published; the usage contract explicitly instructed area owners to unpack the archive for validation and commit only owned files.

## Implemented

All seven screens use the shared PageLayout/Calm PageHeader, cards, fields, chonk actions, real-link Pane tabs, badges, skeletons and keyed list transitions:

- `/buyer`
- `/buyer/auctions/[listingId]` (same maximum form as the watch-detail slot)
- `/checkout`
- `/checkout/[id]`
- `/prices`
- `/buying`
- `/inbox`

Removed feature-owned hero sizes, page gutters, accent stripes, legacy palette aliases and control overrides. Feature CSS consumes shared tokens and contains no palette, font-family, radius, shadow-token or keyframe definitions. Existing authorization, access partitions, fee/money parsing, revision/idempotency guards, routes, APIs, copy and unavailable-payment boundaries are unchanged.

### Integrated shared primitives

Select, Switch, CardHead/ToneIcon, compact SectionState, LoadingRows and Notice now come from `@beirut-time/ui`. Their recipes are registered once in the global CSS entry. The physical-coordinate Pane indicator adapter and RTL switch movement live in the shared Arabic stylesheet. Feature sheets retain layout only; no duplicate visual primitive remains.

## Automated checks

Passed against the frozen v3 foundation:

- `corepack pnpm --filter beirut-time-web typecheck`
- `corepack pnpm --filter beirut-time-web lint`
- `corepack pnpm --filter beirut-time-web test`: **66 passed**
- `(cd web && node_modules/.bin/vitest run --config features/proxy-bid/vitest.config.ts)`: **78 passed, 1 opt-in connected test skipped**
- `web/node_modules/.bin/vitest run --config tests/lanes/L07/vitest.config.ts`: **3 passed**
- `web/node_modules/.bin/vitest run --config tests/lanes/L08/web/vitest.config.ts`: **10 passed**
- `git diff --check` for owned paths

The new presentation tests cover shared page composition, true navigation links, menu-backed selects, the controlled USD → LBP → USD switch-back, switch/unread markup, real reservation links, disabled unreleased controls and permission-gated intake/hold forms. Existing behavior tests were not weakened or rewritten.

## Real browser evidence

Evidence directory:

`/Users/andrew/.harness/homes/430-project/firstmate/data/bt-cp-buyer/shots/`

- `matrix-desktop.json`, `matrix-phone.json`: **56 passing cases** — seven routes × EN/AR × light/dark × actual 1440px/390px. Checked locale/direction/theme, one page title and shell, visible layout fit, keyboard focus, phone input text ≥16px and enabled targets ≥44px. The source StickyHeader's intentionally clipped 48px paint veil and invisible tab ruler are not mistaken for visible content overflow; raw scroll widths remain recorded.
- `interactions-en.json`, `interactions-ar.json`: **eight passing groups each**. Currency keyboard selection/focus return and switch-back; quote create/review; draft save/edit and disabled send/payment; preference switch with keyboard; read/clear and actual list exit; allowlisted notice navigation; maximum preview/review/acknowledgement; availability/reservation; restricted hold/intake; shared theme transition (the source groups combine related operations).
- `select-switch-back.json`: actual AXI **mouse and keyboard** USD → LBP → USD checks. Both work and return focus. The initial failing reset was a harness assumption: Radix pointer-open and keyboard-open menus do not begin with the same focused radio. The script now focuses the trigger, opens with Enter, and uses Home/arrow/Enter deterministically.
- `states-en-desktop.json`, `states-ar-phone.json`: **52 passing state cases** — loading, applicable empty states, dependency failure and signed-out boundaries across the area. Empty order-detail/auction states are not invented where those domain screens instead require a valid record/live auction. Slow fixtures stay below the real BFF's 1200ms per-dependency budget; dependency-error rounds run last to respect its 10-second circuit-breaker cooldown.
- `control-cp-light/dark.json`, `control-buyer-light/dark.json`: real mouse hover, keyboard-visible focus and active Space press on CP and Beirut Time. Shared controls match normalized colors, 32px desktop geometry, hover face and **130ms standard-eased** press transform. Theme interactions use a real View Transition with **450ms** duration. Inbox clearing visibly exercises the shared exit animation.
- **60 PNGs**: seven Beirut Time routes in every locale/theme/viewport combination (**56**), plus unchanged CP component-reference compositions in EN light/dark desktop/phone (**4**). Files are named `<route>-<locale>-<theme>-<desktop|phone>.png` and `cp-reference-en-...png`.

The AXI session is isolated as `bt-cp-buyer`. Screenshots are captured by a separate headless Chrome process, never the AXI screenshot bridge. On this Mac the plain `--window-size=390 --screenshot` command cropped a wider viewport and could capture pre-hydration placeholders; `capture-shots.mjs` therefore sets an actual 390px device viewport, waits for hydrated fixture data, and captures through headless Chrome. Temporary profiles are removed by the driver.

### Reference and limits

Creator Pipeline was never modified or started in place. Per firstmate instruction, its frontend was copied into `/tmp/cp-ref-buyer`, installed and run there. A disposable reference composition imports the **original, unchanged** CP PageHeader, CardHead, StateBlock, Select, Button, Input and Settings Switch, with the original styles. Authenticated CP screens needing its unavailable backend were also checked against their source/style recipes as mapped in `CREATOR-PIPELINE-MAPPING.md`; this is not a claim of full authenticated CP workflow screenshots or a pixel-diff baseline.

The CP source's `ar` department means **A&R**, not Arabic. The source has no Arabic/RTL contract. Beirut Time's Arabic uses the frozen foundation's logical-property/font adapters; this report does not invent a source Arabic implementation.

All API browser data is **explicitly synthetic** and confined to a loopback-only fixture through the real app/BFF/client path. Browser results prove presentation and interaction wiring, not real auction outcomes, settlement, payment, custody or production authorization. The existing connected fee proof remains opt-in/skipped. No production API, route, auth bypass or fixture import was added.

## Reproduction tools (never imported by the app)

- `browser-fixture.mjs`: loopback-only fixture on 33516; screenshot-only theme-cookie transport on 33519.
- Application proof server: 33517, with identity/communications/pricing/orders/auction upstreams pointed to 33516 and public origins including 33517 and 33519.
- Disposable CP reference: 33515.
- `browser-matrix.js`, `browser-interactions.js`, `browser-states.js`: run with the isolated `chrome-devtools-axi ... run` command. Explicitly emulate `1440x1000x1` or `390x844x1,mobile,touch`; resize alone clamps to 500px on this Mac.
- `browser-control-states.sh`: source/port shared-control comparison.
- `capture-shots.sh` / `capture-shots.mjs`: set `BT_BUYER_SHOTS` to the evidence directory.

Own AXI session and proof servers are stopped at delivery. No push, merge, pull request, no-mistakes run, CI or Jira change was performed.

## Area snapshot paths before shared-primitive promotion

```text
web/app/(buyer)/buyer/auctions/[listingId]/page.tsx
web/features/buy-now/checkout.tsx
web/features/buy-now/hold-control.tsx
web/features/buy-now/order-detail.tsx
web/features/buy-now/styles.css
web/features/buy-now/watch-slot.tsx
web/features/inbox/page.tsx
web/features/inbox/styles.css
web/features/inbox/switch.tsx
web/features/pricing/buying.tsx
web/features/pricing/patterns.css
web/features/pricing/patterns.tsx
web/features/pricing/quotes.tsx
web/features/pricing/select-menu.tsx
web/features/pricing/select.tsx
web/features/pricing/shared.tsx
web/features/pricing/styles.css
web/features/proxy-bid/CREATOR-PIPELINE-MAPPING.md
web/features/proxy-bid/VALIDATION.md
web/features/proxy-bid/browser-control-states.sh
web/features/proxy-bid/browser-fixture.mjs
web/features/proxy-bid/browser-interactions.js
web/features/proxy-bid/browser-matrix.js
web/features/proxy-bid/browser-states.js
web/features/proxy-bid/buyer-workspace.tsx
web/features/proxy-bid/capture-shots.mjs
web/features/proxy-bid/capture-shots.sh
web/features/proxy-bid/presentation.test.tsx
web/features/proxy-bid/proxy-bid.tsx
web/features/proxy-bid/styles.css
```
