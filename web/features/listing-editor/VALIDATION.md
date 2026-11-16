# Seller-area port validation

## Foundation and scope

Historical checks used the first frozen shared foundation. No registrations, routes, API adapters, access policy, EN/AR dictionaries, or business-state models were changed.

Page compositions are documented in [PAGE-PATTERNS.md](PAGE-PATTERNS.md).

## Checks

- Web ESLint and TypeScript: pass.
- Web foundation tests: 66 pass.
- Listing-editor tests: 11 pass, including four shared-control markup tests.
- Auction-management tests: 61 pass. The organization-grant test now checks options supplied to the lazy Select instead of expecting unopened menu options in server HTML.
- Real Chrome checks: all four pages in EN/AR, light/dark, 1440×1000 and mobile/touch **390×844**. Initial page matrix: 32 checks, no page errors or horizontal overflow. Desktop fields: 13px/36px; phone fields: 16px/44px.
- All four editor steps: 32 further layout/motion checks. Shared `pg-contentIn` entry, measured Pane key and single-line/tiled fit were checked. Both EN and AR phone labels fit inside their tiles without overlap.
- Empty lists, failed list/dashboard/editor/auction reads, and auction sign-out: 56 state checks spanning both languages, themes and widths. Every expected calm face appeared without horizontal overflow.
- Live interactions checked: listing creation navigates to its real draft route; dirty/save/revision transitions; photo safety gating; authenticated document actions remain present; current fee quote enables publish; auction increment-band insertion; keyboard tab movement; Select opening, Escape and focus return; shared touch-press marking/cancellation; focus ring; shared theme switch invokes View Transitions once and uses the 450ms token. API/authorization/idempotency behavior remains covered by existing tests.

Page/form/dashboard checks used synthetic local API responses in Light/Dark and desktop/phone. They establish presentation and interaction wiring, not production-service availability. RTL follows the shared logical-property and font adapters.

On this Mac, screenshot writing through chrome-devtools-axi is unavailable. All screenshots were taken by headless Chrome from settled, same-origin DOM snapshots of the actual browser pages; animation was frozen for the still capture. Browser interactions, motion and the real 390px viewport were checked live with chrome-devtools-axi. Headless Chrome's minimum 500px window was compensated only in snapshot framing with the live page's measured 390px root width; this does not substitute for the live viewport checks. No screenshot route, fixture server or screenshot helper is part of the committed application.

## Integrated shared primitives

Select, the full Pane HeaderTabs, RowSkeleton and their recipes now live in the shared UI package. Touch press/lift/cancel handlers live in `web/lib/press-look.ts`. ListingSkeleton remains a page-owned composition of the shared RowSkeleton. Direction-aware tab keyboard handling and longer marketplace-label wrapping are retained.

The complete shared glass materials are centralized in the token file and full Pane stylesheet, without feature-local fallback shadows. Server-rendered ButtonLink now uses a server-safe recipe module. No duplicated visual primitive remains in this feature.

## Area snapshot paths before shared-primitive promotion

- `web/features/auction-management/bid-slot.tsx`
- `web/features/auction-management/studio.test.ts`
- `web/features/auction-management/studio.tsx`
- `web/features/auction-management/styles.css`
- `web/features/listing-editor/PAGE-PATTERNS.md`
- `web/features/listing-editor/VALIDATION.md`
- `web/features/listing-editor/components.tsx`
- `web/features/listing-editor/controls.test.ts`
- `web/features/listing-editor/credits.tsx`
- `web/features/listing-editor/dashboard.tsx`
- `web/features/listing-editor/editor.tsx`
- `web/features/listing-editor/header-tabs.css`
- `web/features/listing-editor/header-tabs.tsx`
- `web/features/listing-editor/list-view.tsx`
- `web/features/listing-editor/press-look.ts`
- `web/features/listing-editor/row-skeleton.tsx`
- `web/features/listing-editor/select-menu.tsx`
- `web/features/listing-editor/select.tsx`
- `web/features/listing-editor/styles.css`
