# Seller page patterns

Seller pages compose the shared design system without changing routes, API behavior, permissions, dictionaries or business-state models.

| Page / surface | Shared pattern | Contract |
| --- | --- | --- |
| `/[locale]/seller/listings` | PageHeader, compact listing rows, AnimatedList | Full-width `pg-list-page`; supporting copy and secondary/primary actions. Watch cover, brand/model, reference/location, asking price and state occupy fixed row slots. Preserve scoped links, pagination and create idempotency. |
| `/[locale]/seller/dashboard` | CardHead, `pg-stat-tile`, `pg-workspace-grid` | Restrained draft/published/pending metrics, listing rows and independent activity cards for bids, sales and payouts. |
| `/[locale]/seller/listings/[id]` | Detail header and Pane navigation | Facts, Disclosure, Photos and Review tabs retain real links, back action, revision/demo metadata, dirty/save status and shared content-entry motion. |
| Facts / Disclosure | Card and shared Input/Select/Textarea/Checkbox | Two columns on desktop, one on phone. Preserve bilingual labels, digit normalization, field types, validation and disabled/busy states. |
| Photos / Documents | ImageFrame and upload controls | Reserved geometry and decoded-pixel reveal. Preserve public-photo safety, ordering, cover selection, private downloads and retries. |
| Review / Preview | Fact rows, StatusBadge and secondary card | Quiet fee summary and watch preview. Publish retains quote/idempotency gating. Phone content stacks in DOM order. |
| `/[locale]/seller/auctions` | Form card and adjacent summary | Shared Select/Input/Button; scoped organization picker. Preserve currency, increment bands, secret reserve, UTC schedule and uncertain retry behavior. |
| Empty/loading/error/auth/access | State and RowSkeleton | Preserve bilingual errors, correction fields, request references, sign-in return URLs and retries. A failed read never becomes empty success. |
| Dialogs | Shared dialog/popover primitives | Creation remains its immediate API operation; publishing retains explicit Review. Select inherits direction-aware placement and shared motion. |
| Image credits | Shared image cards and PageHeader | Preserve bilingual attribution, manifest assets and source/license links. |

## Cross-page behavior

- Consume shared typography, spacing, radii, status ink, shadows, hit targets and motion; feature CSS supplies token-consuming composition only.
- EN/LTR and AR/RTL use logical spacing, start/end alignment, isolated references and direction-aware controls.
- Hover, focus, press, disabled, busy, error and selected states come from shared controls.
- At 390px actions wrap, columns stack, long references/dates wrap and tabs stay reachable.
- Reduced motion is owned by the shared kit; no feature keyframes.

See [the design contract](../../../docs/design-system.md) and [validation](VALIDATION.md).
