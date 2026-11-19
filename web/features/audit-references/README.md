# Audit references

The private `/operations/audit` view requires the canonical root shell and its shared read scope. The current shared route selection does not supply them for this address, so the published route cannot yet query owners. The view uses the canonical page, field, select, dialog, state and placeholder components. Locale changes leave form and query state mounted. Only an access fingerprint change replaces the form. The selected organization comes from current identity, never a translated label. The query operation reference stays visible and editable for recovery after restart; unsent inputs stay in memory.

The shared page read keys are `audit-references.v1` plus access fingerprint, source and complete query, and `audit-operation.v1` plus access fingerprint, source, organization, exact operation and revision. Reads use the root provider, a zero freshness window and open-only warming. There is no background polling or automatic retry. Answers are held only by the shared access-partitioned memory cache; each opening rechecks the owner. Failed reads suppress held private answers. Each source pages independently with its own source revision and server total.

The six speed methods follow the shared boundary: ready-before-press route preparation belongs to the root page registry; data-on-intent uses the same read definition; answers between visits use shared memory; refresh retains current content until a failure; placeholders belong only to the first answer; one shared arrival fade covers the answer. No feature creates a provider, shell or timing recipe. Registration and per-page size measurement belong to the runtime composition owner. If the shared read scope is absent, the owned read boundary preserves the form and shows unavailable recovery without mounting another provider. The first frame uses the root theme/font/session order and an honest session or read placeholder, never invented records.

Source dates are UTC. Display uses Asia/Beirut and explicit locale digit systems. This view creates no civil appointments, commercial amounts, uploads or execution permissions. Reason references open an owner-mediated operation lookup, with no raw evidence route. Changing language triggers no submission.

## Feature declaration

`delivery-contract.json` declares the route, page, feature view, content locator and private read policy using the page-table fields. The view composes the shared `PageFrame`, `PageHeader` and `usePageRead` boundaries. Both private reads remain `open-only`.

The separate foundation change consumes feature declarations and supplies the canonical shell and access-partitioned read scope. Shared page tables, validation and shell selection are outside this module's ownership. Until that composition is present, the route cannot query owners; a missing declaration diagnostic or shared scope remains a deferred composition prerequisite.

A missing shared read scope preserves the form and shows unavailable recovery without mounting another provider or offering an ineffective retry. Owner failures offer the same-reference retry once the shared scope is present. The scope tests exercise the real shared read and arrival components; server rendering does not execute a query or prove owner access.

After foundation composition, verify submitted queries reach every owner, retain the exact operation reference on retry and clear private answers after access changes. Connected permission, navigation, page size, first-frame and browser geometry proofs remain owed.
