# Seller-area Creator Pipeline mapping

Source (read-only): `creator-pipeline-middleware/frontend`.
This mapping was recorded before the shared-kit contract was published; implementation uses that contract when available.

| Beirut Time page / surface | Creator Pipeline source pattern | Port contract |
| --- | --- | --- |
| `/[locale]/seller/listings` | `components/campaigns/campaigns-view.tsx`, `campaign-row.tsx`, `styles/campaigns.css` | Full-width `pg-list-page`; shared PageHeader title, supporting copy and secondary/primary actions. Compact horizontal campaign rows, not the former large image gallery. Watch image takes the cover slot, brand/model the name, reference/location the metadata, asking price the budget, listing state the status. Shared AnimatedList handles arrival/removal. Keep scoped links, pagination and create idempotency. |
| `/[locale]/seller/dashboard` | `components/proto/home/` dashboard boxes; campaign overview `pg-stat-tile` and `pg-workspace-grid` | Shared PageHeader; restrained metric tiles for drafts/published/pending; same compact listing rows; activity boxes for bids, sales and payout with shared card/title/spacing. Registered seller contributions remain independent. |
| `/[locale]/seller/listings/[id]` header/navigation | `components/campaigns/campaign-detail-shell.tsx`, shared PageHeader nav | Same detail hierarchy and shared seam tabs for Facts, Disclosure, Photos, Review. Back link, listing status, revision/demo, dirty/save status and save behavior retained. Tab content uses the kit's content-entry motion rather than feature keyframes. |
| Editor Facts / Disclosure | `components/proto/new-campaign/nc-parts.tsx` Field; `new-campaign-window.tsx` calm/live form | Calm tokenized card, two-column desktop form and one-column phone fields; shared Input/Select/Textarea/Checkbox. No Georgia/Arial overrides. Existing field types, bilingual labels, digit normalization, validation, disabled/busy states and disclosure collection retained. |
| Editor Photos / Documents | New Campaign CoverWell, shared image-frame; campaign settings cover controls | Rounded shared image frame, tokenized upload target and compact shared action controls. Decode reveal uses the shared image-reveal motion token. Public-photo safety gate, ordering, cover choice, authenticated document downloads and retries remain intact. |
| Editor Review / Preview | Campaign overview/financial summary; new-campaign Live card | Quiet label/value summary, shared status badge and tokenized secondary surface for fees; publish action retains quote/idempotency gating. Desktop live watch preview; phone single-column content. No new shadows/colors/radii/keyframes. |
| `/[locale]/seller/auctions` | Campaign settings / New Campaign calm form plus campaign overview summary cards | Shared PageHeader; form card and adjacent summary list, one column on phone. Shared Select, Input and Button; organization picker retains scope isolation. Existing currency, increment bands, secret reserve, UTC schedule and uncertain retry behavior unchanged. Auction summary uses shared badge and label/value detail rows. |
| Empty/loading/error/auth/access | `components/faces/calm-face.tsx`, `components/ui/row-skeleton.tsx`, campaign-list failed-load/empty faces | Shared calm face, row skeleton and card primitives. Preserve bilingual error wording, correction field names, request references, sign-in return URL and retry semantics. Never turn a failed read into an empty success. |
| Dialogs | `components/ui/dialog.tsx` | No new dialog is needed: listing creation stays its existing immediate API operation, and publishing retains its existing explicit Review step. Any kit Select popover inherits shared dialog/popover motion and RTL placement. |
| Image credits (shared feature consumer) | Campaign/creator image cards | Its route is outside the assigned app paths; its existing component lives inside this feature and must remain compatible when replacing feature CSS. Shared card/header and token-only layout styling, preserving image attribution and links. |

## Cross-cutting parity

- Consume the shared theme/font, spacing, radii, status ink, shadows, hit targets and motion; feature CSS only supplies token-consuming composition.
- EN/LTR and AR/RTL use logical spacing, start/end alignment, isolated references and the shared direction-aware controls. No manually mirrored theme animation.
- Desktop hover, keyboard focus, pointer press, disabled, busy, error and selected states come from kit controls.
- At 390px, actions wrap in source order, form columns collapse, long IDs/date values wrap without page overflow, and tabs stay horizontally reachable.
- Reduced-motion behavior comes from the shared kit; do not add feature keyframes.
