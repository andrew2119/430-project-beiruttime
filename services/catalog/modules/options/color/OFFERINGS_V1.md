# Versioned offering maintenance

The four original providers remain separate. Their existing versioned publication
command and exact saved revisions remain authoritative within Catalog. No change
to an offering rewrites a saved configuration or grants feasibility or execution
permission.

Ordinary colleagues require current `business.jobs.write` permission for the
selected business. Business identity, active official-brand capability and current
membership are checked on every publication, form read and receipt lookup,
including retries. Job titles alone confer no permission.

`GET /v1/brand-options/brands/{brand_id}/forms/{kind}` returns
`catalog.offering-form.v1`: the write schema, detail schema, bilingual dimension
label, bilingual recovery states and stable operation paths. The form consumer
keeps field values and the operation reference in memory when changing language.
This endpoint describes forms; mounting them belongs to the shared application.

`PUT /v1/brand-options/brands/{brand_id}/{kind}/{option_id}` takes the existing
option write schema and an `Idempotency-Key` of 8–100 letters, digits, underscores
or hyphens. `expected_revision` is zero for creation and the current revision for
an update or availability change. Each successful command appends one revision
and records its receipt and event intent in the same transaction. A revision
conflict requires explicit reload and review. Do not silently overwrite it.

`GET /v1/brand-options/brands/{brand_id}/operations/{operation_id}` recovers the
original offering receipt for its actor and business. A missing receipt is an
unavailable result, never evidence of success or failure. Retry the original PUT
with the same reference and identical body. A changed body with the same reference
conflicts. Identical retries return the original revision, even after later
updates. Lookup never returns configuration or private-reference receipts.

New receipts add `catalog.offering-receipt.v1` and bind operation, actor, business,
option subject, expected revision and resulting revision. `watch_id` is null:
maintaining an offering never allocates a physical watch. Saved state has no
pending reason or next reviewer. Old receipts retain their original bytes.

Finishing packages require interventions, exclusions, required tests and an
indicative price reference. Active prices are integer USD cents; people enter
and see dollars. `dollar_cents` accepts exact Latin or Arabic digits with at most
two decimal places and never rounds a third decimal. Indicative prices are not
quotes or a promise of feasibility. Old non-USD package definitions remain
unchanged in revision storage, are omitted from active catalogs, cannot be newly
selected, and appear only as a restricted legacy marker in saved configurations.
Reissue the offering in USD and explicitly review new choices. Active operation
lookup and command replay return the same restricted marker for historical
publication and selection receipts, preserving operation references and stored
receipt bytes. Dependency failures provide English and Arabic recovery actions.

Material keeps solid, plating and coating distinct; plating and coating require
substrate and thickness. Dial choices retain original or aftermarket provenance.
Finishing packages describe work rather than a luxury score. Missing compatibility
rules remain for manual assessment by the request consumer; these providers never
invent a compatibility or parts-availability decision.

The deterministic fixtures are synthetic development contracts. They do not
prove current identity, connected publication, transaction durability or completed
work. Shared mounted forms, current dependency integration, database rollback and
restart, and bilingual desktop/phone acceptance require their own connected checks.
