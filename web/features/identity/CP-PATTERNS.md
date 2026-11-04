# Creator Pipeline pattern mapping — account area

Reference frontend (read only): `/Users/andrew/.harness/homes/creator-pipeline/firstmate/projects/creator-pipeline-middleware/frontend`.

This mapping was written before the shared design-system usage contract was available. Product routes, API behavior and existing EN/AR copy remain unchanged; the shared port supplies the visual vocabulary, not new feature-specific recipes.

## `/account`

- Signed out, register, recovery, reset: public auth card (`components/auth/auth-card.tsx`, `styles/auth.css`) and existing login form field/submit vocabulary. Use the same form controls, muted uppercase labels, compact field rhythm, primary/neutral chonk buttons, inline error and success lines.
- Signed in: Settings Profile and Account sections (`components/proto/settings/settings-sections.tsx`): section card with icon/title head, profile summary, account/security panels and neutral sign-out action. No invented account dashboard treatment.
- Mode selection adopts shared Segmented; changing mode uses the shared content/list swap motion, not a feature keyframe.
- Session restoration/retry adopts the shared pending/error face. Native POST fallback, password autocomplete, return paths, error reference and focus restoration must remain intact.

## `/seller/verification`

- Settings Account / two-factor form pattern: shared page header, section card, compact labels and stacked form fields; evidence uploads use shared form control recipe.
- Application status and saved reference use the shared status/fact presentation, not custom colored banners. Auxiliary privacy/demo copy adopts the Settings hint / quiet note vocabulary.
- Loading, request failure and signed-out gate use shared state faces and retry controls. Keep correction/rejected editing, revision fencing, synthetic evidence restrictions and post-submit focus.

## `/consent`

- Settings section cards for the consent form and saved consent records; account-style two-panel layout when space permits and a single column at phone width.
- Explicit agree/refuse remains a native radio decision, styled with Creator Pipeline's radio primitive; never silently default the decision.
- Saved records adopt the Requests/Home list (`components/proto/requests/requests-list.tsx`): hairline-separated records, compact metadata, neutral withdrawal action and shared animated list insertion/removal.
- Privacy, scope and withdrawal guidance use quiet Settings notes. Loading/error/empty use the shared kit faces. Keep bound request/brand/revision values, optional evidence, idempotency and withdrawal focus.

## `/customize`

- Shared page header and Settings / campaign-settings form layout: binding controls in a card, shared Segmented category selector, then selectable option cards.
- Selectable cards adopt Settings Appearance selection (`proto-set-theme`, radio indicator, focus ring, selected depth and press behavior) rather than gold-edged bespoke tiles.
- Summary is a shared card/detail panel. Watch preview is product content (not a new design token); uploaded private dial references retain memory-only image handling.
- No-brand, no-selection, loading, API error and session retry use shared faces. Saved configurations use the shared select. Preserve URL bindings, canonical saved state, access fencing, retry reconciliation and private references.

## `/custom-requests`

- Page header plus Settings-style cards/panels for editor, readiness and saved drafts. Long scope/notes fields use Creator Pipeline's form-control recipe.
- Readiness is a compact fact/list presentation, not a bespoke progress UI: unavailable/not-assessed states must remain honest.
- Saved drafts adopt Requests/Home animated, hairline-separated rows with neutral resume control and quiet timestamp.
- Signed-out, restore/configuration loading and error states use shared calm faces. Keep in-memory draft privacy, idempotency, uncertain-save fencing, locale-change save handshake and linked configuration behavior.

## `/services` and embedded movement option

- List/detail composition borrows Creators/Campaigns list plus Settings detail cards: shared page header; purpose tabs use shared Segmented navigation; business rows/cards use the shared card, icon square, quiet metadata and capability facts.
- Selected business uses the same selected/focus recipe as the kit, not an accent border invented for this feature. Detail panel uses section heading and shared form control for capability.
- Movement option is a Settings form section: shared select, two-column facts, compact text fields, shared notice/status, primary save action.
- Directory loading/error/empty/no-selection and session availability use shared faces. Preserve pagination, selected business URL, detail focus, saved capability restoration, movement revision checks and all roles/API boundaries.

## Cross-page parity checks

- Shared Creator Pipeline tokens/fonts/card depth/button states/page header/motion only. Feature CSS may arrange layout and consume tokens, never introduce colors, fonts, radii, shadows or keyframes.
- All pages: English and Arabic; light and dark; desktop and real 390px viewport; keyboard focus, pointer hover/press, reduced motion and theme transition; no horizontal overflow.
- Browser screenshots go to the assigned `bt-cp-account/shots/` directory. No reference source is modified.
