# Dealer import v1

POST `/v1/seller/imports` accepts UTF-8 CSV as `text/csv`, an `Idempotency-Key` (1–128 characters), and `If-Match: 0`. Maximum 1,000 rows, 1 MB encoded bytes, and 2,000 characters per cell. Columns are exactly `brand,model,reference,year,condition,location,price_usd,serial`. Prices are exact positive USD dollars with at most two decimal places; stored values are integer cents.

GET `/v1/seller/imports/{operation_id}?offset=0&limit=50` returns the current private operation, server totals and paginated row outcomes. Every access checks current dealer sales membership. An operation is bound to actor and selected organization. Cross-scope access is denied. A changed body under the same operation conflicts. Initial expected revision is zero; settled receipt revision is one. Retrying the identical operation after a lost response returns the original receipt. Invalid rows are isolated; malformed CSV structure rejects the table. Cell values never appear in error messages. Formula-like cells are rejected. Exports prefix dangerous cells with an apostrophe before CSV quoting.

Successful rows are canonical private listing drafts, without photos, possession approval, registration, fee acceptance or publication. Missing disclosures must be completed in the listing editor. Publication uses the existing explicit listing publication command with current revision, current authority, reviewed fees, photos, disclosures and canonical physical-watch registration. Import never allocates or publishes stock. Reused normalized serials within the import path cannot create another draft, even under a new operation or organization. A private serial digest is never a public identity or proof of ownership; the canonical registration fence remains authoritative across other routes.

Receipt and row writes share one Catalog transaction. No CSV bytes or serials enter events, logs or response previews. Stable operation lookup survives restart. Dependency uncertainty returns unavailable; retry the same reference. Runtime route and migration composition belongs to the service registration owner.

## Canonical registration boundary

The current publication provider does not accept a normalized serial binding. The additive database guard therefore keeps every imported listing private, including after edits, until the canonical provider integration replaces that guard with a current serialized identity check. Publication is unavailable for these drafts; staff must complete canonical registration integration before requesting it. No connected publication proof is asserted.

## Operation bindings

Every successful create, replay and lookup returns the same persisted envelope: `schema_version, operation_id, subject_id, watch_id, actor_id, organization_id, expected_revision, state, revision, pending_reason, next_actor, next_review_at`, plus totals and paginated items. The batch has no single subject or watch, so `subject_id` and `watch_id` are null; row `listing_id` identifies each private draft. Actor and organization are the immutable authenticated admission scope, never supplied by the CSV. Expected revision is zero and settled revision is one. A settled batch has null pending reason, next actor and next review instant. Denied, stale and unavailable requests return errors without inventing a settled envelope; uncertainty requires lookup or identical replay under the original operation reference.

Current authority is rechecked after upload, after serial admission locks and before receipt completion. Any lost permission or changed actor/business aborts the transaction, including its drafts and events. A serialized cross-service revocation fence remains a connected prerequisite; these checks do not claim distributed atomicity with membership changes.

## Deferred activation

`module.pending.json` describes the intended L20 composition but is not a discoverable registration. The current loader accepts only L01–L11 module and migration prefixes. The service registration owner must extend that contract before activating this manifest and its migration. The import endpoints remain inactive until that composition lands; local command checks do not assert connected availability.
