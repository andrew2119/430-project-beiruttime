# Visitor discovery page patterns

Discovery composes the shared design system. Product data, routes, EN/AR copy, privacy boundaries, money formatting and polling remain Beirut Time's.

| Page | Shared pattern | Contract |
| --- | --- | --- |
| Dashboard `/` | PageHeader and section-door cards | Permission-filtered registered destinations, not a second marketing landing page. |
| About `/about` | State / Calm face | Existing three promise paragraphs and back action. |
| Browse `/watches` | Header and animated card grid | 230px minimum tracks, 16px gaps and reserved 208px media. Preserve title, mode/state, model/location, price and demo disclosure. |
| Search `/search` | Browse grid and header controls | Shared search/submit row. Preserve filters, saved-search disclosure, currency, minor-unit ranges, mode, sort, reset, copy and cursor links. |
| Watch `/watches/[id]` | Detail header and two-column cards | Reserved gallery and facts for modifications, seller and assurance. Unavailable/not-found uses State, never stale purchase controls. |
| Gallery and zoom | ImageFrame and Dialog | Same-origin public media, decode reveal, two bounded retries, thumbnails, full-resolution scroll, focus restoration, Escape and previous/next controls. |
| Live bids | Fact cards, badges and AnimatedList | Only new bids enter individually. Preserve clock countdown, sequence reconciliation, offline masking, revisions, polling and cleanup. |
| `/image-credits` | Image cards and PageHeader | Preserve manifest assets, bilingual descriptions, authors, license/source links and demo disclosure. |

## Cross-page behavior

- Skeletons reserve destination geometry; empty/error/unavailable uses shared state faces and current retry/refusal semantics.
- Page/content/list/dialog motion comes from shared primitives, not feature keyframes.
- Buttons, fields, Select and badges own control states. Native disclosures remain keyboard-accessible.
- Theme and direction are shell-owned. Preserve translations, bidi isolation, logical spacing, mirrored arrows and responsive stacking.
- Real 390px phone layout keeps one content/scroll owner, wrapping controls and one card track with shared hit targets.

## Validation record

Historical integration checks against the shared foundation:

- Web typecheck and lint passed; web suite: 7 files / 66 tests.
- Discovery URL/media policy and live-auction projection: 2 files / 10 tests; expectations unchanged.
- Whitespace checks passed.
- Home, About, Browse, expanded Search, Watch, Credits, empty/unavailable search, missing watch and invalid ranges: EN/AR, light/dark, 1440px desktop and real 390×844 phone.
- Photo dialogs, connected bids and Select menus: the same eight combinations, with extra focus/hover/loading/offline checks. No horizontal overflow in the main 80-case matrix.
- Interactions covered Arabic digits, hidden form values, RTL menu direction, URL state/copy, thumbnails, Escape/focus restoration, theme, polling, offline price masking and a synthetic live bid arrival using `data-list-enter`.

All populated API data was synthetic and loopback-only through real BFF/API paths. Screenshots used actual device emulation; plain headless window sizing was not accepted as phone evidence. These checks establish presentation and wiring, not production availability or real auction outcomes. No fixture or browser helper is imported by the app.

Select/menu, ButtonLink, shell and Arabic fonts are centralized. Photo dialogs restore trigger focus and center full-resolution content in both directions. No feature palette, typography or motion override remains.

See [the design contract](../../../docs/design-system.md) and [shared verification](../../../docs/design-verification.md).
