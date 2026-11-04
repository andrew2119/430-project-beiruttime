# Account-area delivery and validation

## Shared foundation

Built from `bt/cp-design`'s frozen v1 contract and temporary `foundation-v1.tar.gz` overlay. The overlay is **not** included in this area's commit; the integrator must supply the shared foundation. All six routes stay inside the existing shell and registrations. No API/session modules, routes, EN/AR JSON copy or permission contracts were changed.

## Shared ports after integration

- `packages/ui/src/auth-card.tsx` and `auto-height.tsx`: Creator Pipeline `AuthCard` (product mark substituted; h2 because the shared PageHeader owns h1) and Settings `AutoHeight`.
- `identity/styles.css`: their original token-based recipes plus CP's `pg-form-field` / `pg-form-control` vocabulary for native selects, file inputs and the existing nested labels. This avoids replacing native form behavior with a different select implementation.
- Other controls, state faces, status badges, segmented thumbs and animated lists use `@beirut-time/ui`; every page header uses `@/shell/page-header`.
- No feature palette, font family, token declaration or keyframe was added. Selection depth and hover/press transitions consume CP's existing tokens/recipes.

## Automated checks

All passed against frozen foundation v1:

```sh
pnpm --filter beirut-time-web typecheck
pnpm --filter beirut-time-web lint
pnpm --filter beirut-time-web test                         # 66 tests
cd web
npx vitest run --config features/identity/vitest.config.ts # 14 tests
npx vitest run --config features/brand-options/vitest.config.ts # 34 tests
npx vitest run --config features/service-directory/vitest.config.ts # 6 tests
```

The new six markup tests cover EN/AR shared headers, directory loading/error faces, embedded movement controls and request-draft field names/native POST. Existing identity fallback/idempotency/access tests and brand-option canonical/private-state tests were unchanged.

## Browser evidence

Evidence directory: `/Users/andrew/.harness/homes/430-project/firstmate/data/bt-cp-account/shots/`.

- 48 page cases: account, consent, seller verification, customization, private requests and services (including embedded movement); EN/AR × light/dark × 1440px desktop / actual **390px** device-emulated phone.
- `browser-matrix.json` records live DOM checks. Every case had the expected shared header and no document-width overflow. Phone widths were verified with `innerWidth === 390`; CLI `resize` on this Mac was a no-op, so real DevTools device emulation was used instead.
- Private visual states used memory-only synthetic fetch fixtures in the isolated browser. No real credentials, evidence or backend mutations were used. Existing API behavior was covered by the unchanged tests, not claimed as end-to-end backend validation.
- Eight supplemental captures cover sign-in/register/recovery/reset in both languages. `interactions.json` records native POST/required validation and input focus; keyboard Space activated account mode selection, pointer hover was observed, and the real theme control invoked one View Transition with 450ms fades.
- CP reference was run from the authorized disposable `/tmp/cp-ref-account` copy, never in the read-only source. Four `cp-auth-en-{light,dark}-{1440,390}.png` captures show its actual public auth recipe. Authenticated CP Settings/Requests screens lacked a working backend, so those comparisons use the source components/styles specified in `CP-PATTERNS.md`, as authorized by firstmate.
- CP does not implement Arabic (its `ar` area means A&R). Arabic checks therefore validate the foundation's RTL adapter, not a nonexistent CP Arabic page.

### Screenshot transport

Final PNGs were written by the headless Chrome executable, not the CLI screenshot command. They render full DOM snapshots saved from the live checked browser, with scripts removed and the actual app/reference CSS and fonts retained. This preserves synthetic private states without persisting credentials. Chrome's standalone 390px capture internally used a larger minimum desktop viewport on this Mac; the snapshot root was pinned to 390px at the left edge for capture. The interactive checks independently used a genuine 390px emulated viewport. Screenshots reset scroll to the top; they are visual evidence, not a pixel-diff assertion against unavailable authenticated CP screens.

## Integrated typography and shared primitives

The shared layout disables Lexend's broad generated fallback. Fresh browser inspection confirms both the Lexend and Arabic faces load; Arabic no longer falls through to the Latin face's system fallback. AuthCard and AutoHeight now live in the shared UI package, with source auth/settings recipes in the global entry point. No feature font override is used.
