# Fixed-end policy rework checks

The revised auction rules supersede the earlier extension and purchase proof. Earlier scripts and ignored artifacts are historical only; they are not acceptance evidence for this revision.

## Focused checks on 16 November 2026

- 31 Python unit cases passed: fixed deadlines for manual/proxy/ceiling-only bids at 120 seconds, 90 seconds and just before zero; rejection at/after zero; legacy setting inertness; removed configuration rejection; reserve/privacy and historical request replay/exclusion.
- 10 policy UI/API tests passed, both languages: no purchase/configuration controls or checkout links, private reserve comparison and actor-scoped historical reads.
- Web TypeScript check, policy/registration ESLint and changed Python import/syntax lint passed.

The connected engine regression file now expects unchanged scheduled ends, including two proxy rows. It requires the provider kernel and a real isolated database and was NOT run on this Mac.

## Boundaries still owed

L13 retains closing/cancellation and Orders financial release authority; L14 retains canonical lock/mode mutation. Fixtures under `packages/contracts-auction/policy/` are examples, not proof of a cancellation race or a released financial commitment. Connected no-bid close, cancellation versus first bid, historical financial resolution, additive migration integration and real-browser EN/AR/theme/390px checks remain deferred. No Docker, browser, dev server, build, full suite, CI or push was run for this revision.

The policy API publishes version 2 while preserving actor-owned historical operation reads. A 404, timeout or denied allocation cannot authorize another allocation or release. Historic non-USD money is not converted or shown in active forms/totals. Fixed-price purchase code is untouched.
