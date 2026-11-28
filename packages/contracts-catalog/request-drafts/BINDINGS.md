# Current request bindings

Submitted configuration and content revisions remain unchanged. Current watch and
responsibility are separate, versioned facts; a watch reference never binds them.

Orders publishes `POST /internal/v2/customization-requests/{id}/owned-watch` only
from an actual owned-watch operation. Its signed service identity must be `orders`.
The exact WatchBinding command contains operation_id, source_revision,
expected_binding_revision, request_revision, buyer_id, brand_id and watch_id.
Service Operations publishes `/assignment` from the current responsible assignment
operation, with its own signed service identity. AssignmentBinding adds assessor_id,
approver_id, quality_reviewer_id and recovery_operator_id. These are authoritative
producer commands, never browser declarations. Producers must serialize current
ownership and assignment admission with publication; source_revision is monotonic
per request and producer. Retain and retry the identical operation after a lost
response. A reused operation with different content conflicts.

Assessor, approver and quality reviewer must differ, and none of the assigned
people may be the buyer. Changing the watch clears all assignments. Pending or
approved decisions prevent rebinding until reconciled. A source revision or request
revision mismatch requires a fresh read. No historical submission is rewritten or
backfilled from free text.

Authenticated source services can read `/internal/v2/customization-requests/{id}/bindings`.
Authorized buyers and current brand staff can read `/v2/customization-requests/{id}/bindings`
and `/bindings/revisions` (the latest 100 immutable binding revisions). The decision
module reads watch_id and recovery_operator_id from the current request row.

Connected publication from owned-watch and responsible-assignment operations, and
current binding fencing in the decision lifecycle, require the respective source
and decision changes. Until those are connected, absence remains unavailable.
