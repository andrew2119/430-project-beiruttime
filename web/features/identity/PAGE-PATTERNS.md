# Account page patterns

The account area composes the shared design system. Product routes, API behavior and EN/AR copy remain unchanged.

## `/account`

- Signed-out, registration, recovery and reset modes use AuthCard, common field/submit controls, compact labels and inline success/error messages.
- Signed-in mode uses section cards for the profile summary and account/security panels, plus a neutral sign-out action. No invented dashboard or profile-edit API.
- Mode selection uses Segmented and shared content motion. Restoration/retry uses the shared pending/error face.
- Preserve native POST fallback, password autocomplete, return paths, error references and focus restoration.

## `/seller/verification`

- Shared page header, section card, compact labels and stacked fields; evidence uses shared upload controls.
- Status/reference facts and quiet privacy/demo notes use the common vocabulary, not custom colored banners.
- Preserve correction/rejected editing, revision fencing, synthetic-evidence restrictions, sign-out/error boundaries and post-submit focus.

## `/consent`

- Form and saved records use section cards; two columns where space permits, one on phone.
- Agree/refuse remains an explicit native Radio decision, never silently defaulted.
- Saved records use hairlines, compact metadata, neutral withdrawal and AnimatedList.
- Preserve request/brand/revision bindings, optional evidence, idempotency and withdrawal focus.

## `/customize`

- Binding controls in a form card, Segmented categories and selectable option cards use shared focus/selected/press states.
- Summary uses a shared detail card; watch preview is product content, not a token. Private dial images stay memory-only.
- Preserve canonical saved state, URL bindings, access fences, retry reconciliation, private references and truthful empty/error/session boundaries.

## `/custom-requests`

- Editor, readiness and drafts use PageHeader and shared section cards/fields.
- Readiness uses compact facts; unavailable/not-assessed remains honest.
- Drafts use animated hairline-separated rows, quiet timestamps and neutral resume controls.
- Preserve in-memory privacy, idempotency, uncertain-save fencing, locale-change save handshake and linked configuration behavior.

## `/services` and movement option

- Business rows and detail cards use PageHeader, Segmented navigation, quiet metadata, capability facts and shared selection/focus states.
- Movement editing uses Select, paired facts, compact fields, notice/status and a primary save action.
- Preserve pagination, selected-business URL, detail focus, saved capability restoration, movement revisions and API/role boundaries.

## Cross-page checks

Consume shared tokens, fonts, card depth, controls, header and motion only. Feature CSS supplies layout, never new palettes, typography, radii, shadows or keyframes. Validate EN/AR, light/dark, desktop/real 390px phone, keyboard focus, hover/press, reduced motion and theme transitions with no horizontal overflow.

See [validation](VALIDATION.md) and [the design contract](../../../docs/design-system.md).
