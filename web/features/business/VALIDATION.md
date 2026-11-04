# Business / operations Creator Pipeline port

## Delivery

All nine routes in the mapping now consume the shared Calm header, Pane tabs, native-backed CP controls, cards, status badges, calm state faces, skeletons and shared motion. Feature CSS contains layout/token consumers only: no palette, font family, radius value, shadow value or keyframe definitions. Existing routes, transports, permissions, revision/idempotency guards, private-state ownership and translations remain in place. One translated empty-membership message was added.

Validated against `foundation-v4.tar.gz`. That temporary foundation overlay is **not** part of this area's commit. It must be supplied by the integrator. The branch was initially based on the local `bt/cp-design` tip and is rebased onto the current default before delivery.

### Primitive promotion

No unpromoted visual primitive remains. The CP lazy single-choice Select was initially ported locally; v4 centralized it, so the duplicate was deleted. `form-select.tsx` is only a native form adapter around the shared Select: it preserves FormData, native change handlers, reset, draft recovery and explicit direction. It is also used by the moderation/intake pages.

## Checks

- Full web ESLint, TypeScript and production build pass against the frozen kit.
- 66 web tests plus 15 business/moderation tests pass.
- 72 ready-state browser combinations: all nine routes × EN/AR × Light/Dark × actual 1440px/390px viewport. No document overflow or clipped live tab labels; phone input text is at least 16px. Membership lookup, selected verification and selected intake details were opened in the matrix.
- 50 additional phone state checks: 14 empty, 18 loading, 18 unavailable, across EN/AR.
- EN/AR interactive proofs cover contact channel selection, Arabic phone/code normalization, challenge/code reveal/verification, native FormData/reset, report-to-case navigation, intake currency/checkbox/Arabic fee entry. The synthetic transport confirms idempotency keys, revision `If-Match: 1`, normalized contact recipients and numeric fee payloads.
- Keyboard focus rings, menu open/close and Escape focus return were exercised. Menu entry is `pg-slideUpAndFade` on the 200ms step; the theme button invokes the View Transitions API once on the shared 450ms step. Real pointer hover/press states were checked on the shared raised button (its motion is on the inner face/pseudo-element, not the button box).
- Public draft round-trip checks retain public name/type/capabilities while legal name and assurance fields stay private. Restoration notifies the local Select bridge without triggering form-level autosave halfway through recovery.

## Browser evidence

76 PNGs are under:

`/Users/andrew/.harness/homes/430-project/firstmate/data/bt-cp-business/shots/`

Names are `<business|contacts|membership|history|verification|intake|moderation|dashboard|queue>-<en|ar>-<desktop|phone>-<light|dark>.png`, plus four `cp-reference-controls-*` images. Phone images are captured from an asserted real 390px viewport, not a cropped 500px Mac window. Each capture waits for the actual data and font-ready promise.

The browser is an isolated `chrome-devtools-axi` session, `bt-cp-business`, attached to our own headless Chrome. This Mac's MCP screenshot writer denies both task-worktree and evidence paths, while plain `--window-size=390` creates a 500px CSS viewport and crops the PNG. Following firstmate's approved headless-Chrome fallback, only native `Page.captureScreenshot` bytes bypass that writer; all navigation, emulation and interaction stays in chrome-devtools-axi.

Creator Pipeline was run only from `/tmp/cp-ref-business`, a disposable copy of the read-only reference. Its authenticated Settings/Approvals pages redirect to login without its backend. As authorized by firstmate, comparison therefore combines the actual source/styles with a disposable gallery mounting its **unmodified** PageHeader, Settings/Approvals classes, Input, Checkbox, Select and Button. No original CP file was changed. CP has no Arabic/RTL frontend (`ar` means A&R); Arabic adaptation is the shared Beirut Time kit's contract, not claimed source parity with a nonexistent screen.

### Shared-kit follow-up

Resolved in the integrated foundation: Lexend's broad generated fallback is disabled, and live browser inspection confirms the Arabic face loads. The common kit supplies the RTL font and measured indicator adapters; no feature font override is used.

## Reproduction

The scripts in `proof/` are isolated, loopback-only browser fixtures, never app imports or production routes. Use a free set of ports if these are already occupied.

1. Start `node web/features/business/proof/fixture.mjs` (3358).
2. Build the app with the shared foundation. Start on 3357 with Identity/Trust/Communications/Service Operations API URLs pointing to `http://127.0.0.1:3358` and `BT_PUBLIC_WEB_ORIGINS=http://127.0.0.1:3357,http://localhost:3357`.
3. Launch an isolated headless Chrome on remote-debugging port 3360; keep its generated profile under the ignored `proof/node_modules/.runtime/` directory so browser-downloaded JavaScript is not linted as application code.
4. Set `CHROME_DEVTOOLS_AXI_SESSION=bt-cp-business` and `CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:3360`. Use `chrome-devtools-axi emulate --viewport '1440x1000x1'` and `'390x844x1,mobile,touch'`, running `chrome-devtools-axi run < .../proof/browser-matrix.js` at each size. The other proof scripts use the same runner.
5. `state-matrix.js` uses fixture modes `/__proof?mode=empty|slow|error`; set the current body's `dataset.proofMode` to the same value before each run. Return the fixture to `ready` afterward.
6. `capture.mjs` writes the screenshot matrix. Its four reference shots additionally expect the disposable CP gallery on 3356 and `screenshot-proxy.mjs` (3352/3353 supplies CP's existing SSR theme cookie).
7. Stop only these owned processes and the named browser session when finished. No backend database, shared runtime, Herdr process, remote branch or pipeline is involved.

## Exact committed path manifest

```text
web/features/business/CREATOR-PIPELINE-MAPPING.md
web/features/business/VALIDATION.md
web/features/business/ar.json
web/features/business/boundary.test.tsx
web/features/business/boundary.tsx
web/features/business/components.tsx
web/features/business/contacts.tsx
web/features/business/controls.test.tsx
web/features/business/directory.tsx
web/features/business/drafts.ts
web/features/business/en.json
web/features/business/form-select.tsx
web/features/business/history.tsx
web/features/business/membership.tsx
web/features/business/proof/.gitignore
web/features/business/proof/browser-matrix.js
web/features/business/proof/capture.mjs
web/features/business/proof/control-states.js
web/features/business/proof/draft-recovery.js
web/features/business/proof/fixture.mjs
web/features/business/proof/interactions.js
web/features/business/proof/screenshot-proxy.mjs
web/features/business/proof/state-matrix.js
web/features/business/review-history.tsx
web/features/business/styles.css
web/features/business/verification.tsx
web/features/business/vitest.config.ts
web/features/moderation/common.test.tsx
web/features/moderation/common.tsx
web/features/moderation/dashboard-screen.tsx
web/features/moderation/evidence-panel.tsx
web/features/moderation/intake-screen.tsx
web/features/moderation/moderation-screen.tsx
web/features/moderation/session-boundary.tsx
web/features/moderation/styles.css
```
