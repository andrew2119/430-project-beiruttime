# Listing eligibility v1

Proposed consumer contract; connected provider acceptance remains deferred.
`eligibility.py` defines the strict private response. No evidence bytes, serial,
private reference or reviewer identity belongs in this response or public events.

Operation lookup: authenticated Catalog calls Identity
`POST /internal/v1/listing-eligibility/validate`, using the publication operation
key as `Idempotency-Key`. The request is the response binding subset:
`schema_version,operation_id,subject_id,listing_id,watch_id,actor_id,organization_id,expected_revision,identity_digest`.
The digest covers normalized brand/model/reference/year/modification facts.
A changed identity needs fresh proof. Relisting requires a fresh listing binding.

The provider rechecks current identity, permission, business scope, listing-specific
review and canonical physical-stock duplicate review on every call, including
retries. A prior eligible response cannot authorize a later publication. Its
serialized validation must protect publication admission against concurrent
revocation and duplicate registration before connected acceptance.

Every private listing needs a consumed single-use code and private watch photo,
submitted from code issue inclusive to issue plus 24 hours exclusive, and current
assigned review. Seller approval alone is insufficient. Business listings still
need current authority and duplicate review. Normalized private serial/reference
comparison belongs to the canonical physical-stock provider; Catalog never
creates an independent allocation authority.

`pending`, unknown, malformed, stale, mismatched or unavailable responses keep
publication private. Initial preflight runs before freezing the draft; its stable
operation identity is derived from listing, actor and command key, so the same
retry does not rotate the validation identity. A retained edit or publication
keeps that same operation while pending. Explicit `denied` or duplicate `denied`
before intent persistence permits correction. A denied review after an edit intent
exists stays pending until current review and remote fences are reconciled;
a local denial never erases a possibly prepared remote operation. Only `eligible`, `current:true`, exact bindings and
`duplicate_review:clear` can proceed to canonical registration. The check runs
before registration and again before public projection. Atomic provider admission,
revocation races and duplicate serialization remain connected prerequisites.

The response includes the stable envelope: `schema_version,operation_id,subject_id,
watch_id,actor_id,organization_id,expected_revision,state,revision,pending_reason,
next_actor,next_review_at`. `subject_id` equals `listing_id` and is checked against
the requested listing. `expected_revision` binds the listing version; `revision`
is the positive eligibility decision revision, not a replacement listing version.
Recovery fields are required and nullable outside pending states. A pending response
requires a reason, responsible role in `next_actor` (never a reviewer identity),
and a timezone-aware review instant in `next_review_at`. Catalog returns only these
recovery fields and the operation/subject/decision revision in pending error details,
so recovery retains the same operation without exposing possession evidence.
