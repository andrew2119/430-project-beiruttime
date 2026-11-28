# Fixed-end policy rework checks

The revised auction rules supersede the earlier extension and purchase proof. Earlier connected scripts and ignored artifacts are historical only, not acceptance evidence for this revision.

## Focused checks on 16 November 2026

- 50 Python unit cases: unchanged manual/proxy/ceiling-only ends at 120 seconds, 90 seconds and just before zero; refusal at/after zero; inert legacy settings; removed configuration; reserve/privacy/current seller access; actor-owned replay; historical read-only Orders lookup, lease fencing and distinct held refusal/unknown/conflicting outcomes. Old terminal receipts remain unchanged.
- 10 policy UI/API cases in both languages: no purchase/configuration controls or checkout links, private reserve comparison and actor-scoped historical reads.
- 86 auction-management cases: exact dollar/cents handling, non-USD archival guards, draft restoration, current projections, role checks and retained operation context.
- 15 server scheduling cases: Beirut winter/summer offsets, missing/repeated local times, explicit interpreted-time review, stable operation/business scope, origin/sign-in/bounded-body checks and removed-setting refusal.
- 20 existing gateway origin/authentication regression cases.
- Web TypeScript, changed-file ESLint and changed Python import/syntax lint passed.

The connected engine regression file now expects unchanged scheduled ends, including two proxy rows. It requires the provider kernel and a real isolated database and was not run on this Mac.

## Provider and evidence boundaries

L13 owns actual closing/cancellation and Orders financial release; L14 owns canonical lock/mode mutation. Cancellation-race/no-bid-close fixtures are handoffs, not proof of a cancellation or released commitment. Orders v3 does not yet publish the exact historical no-attempt release receipt, so a known allocation refusal stays release-pending; unknown or contradictory money stays held. L12 never creates another allocation on 404, reopens bidding or performs a local unfence.

Versioned historical readers derive ended-review state from server time before the worker runs. Legacy request/allocation bindings and old v1 terminal receipts remain intact. Non-USD historical amounts are not converted or shown in active customer forms/totals. Fixed-price purchase code is untouched.

Additive migration integration, actual cancellation versus first bid, real no-sale close, financial release/recovery and real-browser EN/AR/theme/390px input/file/operation preservation remain deferred. The shared locale repair is tracked separately; unit fixtures are not browser evidence.

No Docker, browser, dev server, build, full suite or CI was run. Feature-branch publication was separately authorized; no pull request or merge was opened.
