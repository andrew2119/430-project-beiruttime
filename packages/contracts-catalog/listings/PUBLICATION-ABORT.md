# Publication registration abort v1

Proposed consumer contract. Connected acceptance remains deferred.
Authenticated Catalog calls Orders `POST /internal/v1/watches/registration-abort`
with the publication operation as `Idempotency-Key`. Request and terminal response
bind `operation_id`, `listing_id`, `watch_id`, `actor_id`, `organization_id`, `listing_revision` (the proposed
published revision). A terminal response adds `status:aborted`.

Orders serializes this operation with registration and commitment admission.
Unknown operations create durable tombstones. Later registration with the same
operation must deny. Existing registration can abort only after confirming no
commitment and removing its availability atomically. Committed or conflicting
bindings deny; timeout, absence, denied and malformed replies remain pending.
Identical retries return the exact terminal response.

Catalog durably records review denial before requesting abort, preventing public
projection. Only the exact terminal response unlocks correction, advances the draft
revision and removes the active publication intent. The remote tombstone and old
revision prevent delayed retries from registering or publishing corrected stock.
A new correction uses a new explicit operation. No endpoint implementation is
inferred from these fixtures.
