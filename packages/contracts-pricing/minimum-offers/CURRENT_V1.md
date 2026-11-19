# Private minimum offers v1

The current operation interface is version 1. USD amounts are integer cents,
positive and at most 9007199254740991. People enter dollars. A missing minimum
means manual review. Equal and higher offers require manual review, never
acceptance, reservation, payment or a reserve price.

Authenticated seller routes:
- `GET /v1/minimum-offers/listings/{subject_id}?organization_id=...`
- `PUT /v1/minimum-offers/listings/{subject_id}` with Command.
- `GET /v1/minimum-offers/operations/{operation_id}` with current subject scope.

Command binds schema_version=1, operation_id, actor_id, organization_id,
subject_id, watch_id, expected_revision, source_revision, policy_revision,
quote_id, quote_revision, and minimum_minor (integer or null).
A trusted adapter derives actor identity from authentication, never the body.
Identifiers contain 1–96 ASCII letters, digits, underscores or hyphens.
Bodies are limited to 4096 bytes; calls to the provider have a two-second budget.
Retries use the identical operation and body. Conflicting reuse is denied.

Private results other than denied use the stable envelope
`{schema_version,operation_id,subject_id,watch_id,actor_id,organization_id,expected_revision,state,revision,pending_reason,next_actor,next_review_at}`.
Saved results and current-rule reads add minimum_minor. Current reads use
state=saved and the requested read reference (current by default). Operation
reads return the original receipt's bindings, including expected_revision.
Unknown revision is null; known revision is the actual durable rule revision.
Inactive recovery fields are null. Pending/unavailable bindings echo the request
and do not establish current authority or reveal the private amount.
States are saved, denied, stale, pending and unavailable. Pending carries
pending_reason=source_unavailable, next_actor=seller, next_review_at=null;
retry the same reference. Denied and stale require a fresh authorized read.
No raw exception, private amount or request body is logged or placed in events.
The only outbox event is minimum-offers.changed.v1 with operation, subject,
watch and revision references. Operation reads always recheck current authority.

The provider's `locked(command, actor, timeout_seconds=2)` context holds the
canonical watch serialization fence through the durable local transaction.
It returns current actor, organization, subject, watch, source revision,
policy revision, quote identity/revision, active membership and record grant,
listing mode and commitment. It must fail closed on missing facts. No projected
availability grants permission. This boundary requires Q02 integration before
connected acceptance. No implementation from another service is included here.

Internal offer evaluation is invoked only by an authenticated offers producer
under the same canonical admission fence with current buyer scope and exact
retained offer economics. Below minimum returns only `{state:"declined"}`;
equal/above/absent minimum returns only `{state:"review_required"}`. A block
also returns declined. No reason distinguishes a block from a private minimum.
These results never enter a seller-private rule read API. Buyer requests to any
private route return denied with no amount or revision. Repeated offer admission
and public retry limits remain with the canonical offers producer.

Each party owns its directed block. Removing one directed block cannot delete
the reverse edge. Accepted agreements and retained economics are never edited.
Private rules can change only on current uncommitted fixed-price listings.
