# Creator Pipeline → visitor discovery

Reference frontend (read-only): `/Users/andrew/.harness/homes/creator-pipeline/firstmate/projects/creator-pipeline-middleware/frontend`.

This mapping was prepared before the shared design contract was published. Product data, routes, EN/AR words, privacy boundaries, money formatting, and polling remain Beirut Time's; presentation adopts the reference rather than preserving the previous bespoke visual language.

| Beirut Time page | Creator Pipeline source pattern | Adoption |
| --- | --- | --- |
| Dashboard `/` | `components/proto/page-header/page-header.tsx`, `styles/shell.css` department doors | Shared dashboard with real permission-filtered section doors. The former editorial/marketing home is replaced, not preserved as a second landing page. |
| About `/about` | `components/faces/calm-face.tsx` | Shared Calm face with the existing three promise paragraphs and back action. |
| Browse `/watches` | `components/discovery/DiscoveryClient.tsx`, `DiscoveryPrimitives.tsx` / `VideoGrid`, `VideoCard` | Shared page header; named header/control gaps; animated grid, 230px minimum card tracks, 16px gap, card surface/shadow and reserved 208px media. Existing title, mode/state, model/location, price and demo disclosure remain. |
| Search `/search` | `components/discovery/SearchTab.tsx`, shared page-header controls | Same browse component and data behavior. Search input and submit row follow CP; advanced filters and save-search disclosure retain current behavior with shared controls, token-only layout. Currency, minor-unit ranges, mode, sort, reset, copy and cursor links stay functional. |
| Watch `/watches/[id]` | `components/discovery/ProfilePanel.tsx`, `components/campaigns/campaign-detail-shell.tsx`, overview cards | Shared page header/back control; reserved gallery and token-based two-column detail layout; shared card sections for details, modifications, seller, assurance. Existing unavailable/not-found handling becomes shared Calm face, never a stale purchase control. |
| Gallery and image zoom | `components/ui/image-frame.tsx`, `image-box.tsx`, `components/ui/dialog.tsx` | Preserve safe same-origin public media policy, decoded-pixel reveal and two bounded retries. Use shared media surfaces and dialog entrance/exit/backdrop/focus contract. Keep thumbnails, selected states, full-resolution scroll, keyboard dismissal and previous/next controls. |
| Live bid history | CP overview statistics + `components/ui/animated-list.tsx` row arrivals | Shared statistic/card/badge vocabulary and AnimatedList for new bid rows, no invented bid-highlight keyframe. Keep server-clock countdown, sequence reconciliation, offline/reconnect notices, masking, canonical revisions and polling cleanup unchanged. |
| Image credits `/image-credits` | CP discovery `VideoGrid`/`VideoCard` and shared header | Own page implementation in this area, not feature-specific listing-editor markup. Keep original manifest assets, bilingual descriptions, authors, license/source links and demo disclosure. |

## Cross-page states and mobile/RTL

- Loading: CP skeleton surfaces reserve the shape of the destination cards/detail, not new spinner or decorative treatments.
- Empty/error/unavailable: shared Calm state faces and retry/reset doors; current API refusal semantics remain intact.
- Motion: shared page/content/list/dialog primitives only. Delete feature-defined animation keyframes.
- Controls: shared chonk buttons, inputs, select and badge primitives; native disclosures retain accessible keyboard behavior and use shared control vocabulary.
- Theme: no feature palette; shared tokens and the shell's existing CP theme-transition implementation own light/dark changes.
- Arabic: preserve all existing translations, explicit bidi isolation for identifiers, logical spacing/alignment, mirrored directional arrows and responsive stacking.
- Phone: verify a real 390px browser viewport, retaining the same content/scroll owner, wrapping controls and a single card track; targets follow the shared kit rather than feature overrides.

## Validation record

Implemented against `foundation-v1.tar.gz` from the frozen shared design contract. The foundation was unpacked only for local validation and is not part of this area's commit.

### Automated checks

- `pnpm --filter beirut-time-web typecheck`: passed.
- `pnpm --filter beirut-time-web lint`: passed (after removing disposable browser profiles/test harnesses).
- Web suite: 7 files, 66 tests passed.
- Discovery URL/media policy and live-auction projection suites: 2 files, 10 tests passed, using a temporary Vitest config with the same web aliases and explicit feature includes. No test expectations changed.
- `git diff --check`: passed.

### Real browser evidence

Screenshots: `/Users/andrew/.harness/homes/430-project/firstmate/data/bt-cp-discovery/shots/`.

- Home, About, Browse, Search with expanded filters, Watch detail, Credits, empty search, unavailable search, missing watch and invalid price range: EN/AR × light/dark × desktop 1440×1000 / true 390×844 mobile viewport.
- Photo dialogs, connected bid history and open Select menus: the same eight combinations. Extra hover, keyboard-focus, loading and offline-auction captures are included.
- Zero document horizontal overflow across the main 80-page/state matrix.
- Verified actual bilingual form submission, Arabic-digit range values, hidden Select form values, RTL menu direction, URL state and copied URL feedback; thumbnail switching; dialog Escape and explicit return focus; theme switching through the shell; connected polling; offline masking (`—`, never a stale current price); and a fixture live bid arrival using CP's `data-list-enter` animation (three rows, updated canonical price).
- Interactive checks used isolated `chrome-devtools-axi` sessions. Screenshot writing in that CLI is broken on this Mac, and plain headless `--window-size=390,844` silently lays out at 500px. Final captures therefore use headless Chrome's capture API after the isolated tool sets and confirms a **real** 390px viewport. All browser sessions and local preview/fixture servers were stopped.
- Creator Pipeline ran only from `/tmp/cp-ref-discovery`, copied from the authorized read-only frontend. `cp-reference-*` captures render its actual PageHeader, Select, buttons, discovery VideoGrid/cards and state components. Authenticated/backend-dependent detail comparisons used the original source/styles, per firstmate's instruction. Beirut preview populated/auction states used a clearly illustrative disposable catalog fixture through the real BFF/API paths; error and unavailable service behavior were also exercised. No fixture or browser-harness code ships.

### Integration notes / promotion candidates

1. **Shared Select:** Creator Pipeline's exact lazy single-choice Select and menu now live in `packages/ui/src/select.tsx` and `select-menu.tsx`. Hidden native form fields preserve submitted URL state. Default placeholders and optional search labels also support Arabic.
2. **Server-safe navigation buttons:** ButtonLink uses the shared server-safe button-variants module; no feature-specific client shim or duplicate primitive remains.
3. The photo dialog explicitly returns focus to its trigger and centers its full-resolution scroll area on opening (including RTL). Shared dialog motion, portal, Escape and focus trap remain kit-owned.
4. Shared shell/sidebar/settings and Arabic font provisioning are consumed without feature overrides or a second palette/typography/motion system.
