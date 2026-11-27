# Maintenance requests v1

Submission records reported symptoms, known modifications, private photo references and limited assessment permission. It does not book an appointment, confirm receipt, establish a diagnosis or authorize execution. A destination must support the exact brand and intervention at the current capability revision.

The provider rechecks current identity, ownership, business and brand/intervention permission, exclusive watch commitment and permission to submit private evidence. Photo ownership, retained bytes and expiry are checked in the local write transaction. At most ten files of 256 KiB each are accepted. Metadata stripping and safe-photo declaration remain prerequisites; no pixel detection is claimed. Missing facts return pending; permission denial returns denied; changed revision returns stale. Dependencies have a 1.2-second budget. The transaction factory serializes operation admission, bounds lock waits and commits request, receipt and outbox together. The service resolves current authority inside that transaction after acquiring its operation lock and reading any previous receipt. Connected composition must prove that producer revisions and revocation are fenced through admission across the service boundary. Retry or lookup uses the original operation reference, actor and business. Conflicting reuse denies. Current authority is checked before replay.

The maintenance module registers its routes, migrations and workers together. Producer integration, database rollback/restart and outbox delivery still require connected proof. A fixture is never authority for payment, custody or execution.


The current-authority response has its own strict schema. It echoes actor, subject, operation, watch, organization, brand, intervention and current revisions; every permission flag must be a literal boolean. Context exposes only current eligible destinations. Private photo preparation uses current eligible destination context to check watch and business access. Service Operations validates bytes and declared type, strips metadata, bounds count and size, and durably deduplicates each upload before returning a reference. The request-scoped identity resolver checks current identity. The default provider uses signed Catalog ownership and scope reads, live business capability, and private photo references held within the same Service Operations transaction.

After current permission checks, an identical committed operation returns its durable receipt before comparing source revisions for new admission. A conflicting transport response is resolved through authenticated operation lookup; unavailable lookup preserves the original reference. Changed revisions never turn an uncertain committed submission into a new request.

Closing an unresolved operation uses `DELETE /v1/maintenance/operations/{operation_id}?organization_id={organization_id}`.
A recorded receipt requires current access to its exact buyer, business, watch
and intervention. An absent operation can only be closed under the signed-in
buyer's own actor and requested business, without revealing any other receipt.
Literal false denies access. Invalid or unavailable authority returns 503 and
leaves the original operation unresolved.
The same admission lock returns any committed receipt or
durably closes the uncommitted key for that actor and business. An acknowledged
closure returns `closed: true`, `operation_id` and `organization_id`. A delayed
submission for a closed key cannot commit.

Operation lookup returns `404 operation_missing` for a scoped absent receipt.
A generic route failure leaves the original operation unresolved. Browser
composition requires the context GET, photo POST, request POST, and
operation GET and DELETE routes with authenticated buyer access.

## Assigned assessment

The selected organization can read a submitted request through
`GET /v1/maintenance/requests/{request_id}?organization_id={organization_id}`.
Every read requires current identity and an authoritative `AssessmentAccess`
binding to the caller, organization, assigned request revision, watch, brand
and intervention. The service calls
`assessment_access(actor_id, organization_id, request_id)` before looking up
the stored request. The provider resolves the scope from its current assignment
records. For a caller without access, its response must reveal nothing about
whether the request exists. The service compares an allowed scope with the saved
request before returning data. The provider grants access only with current assignment,
business assessment capability and permission to access the buyer's evidence.
The response carries the submitted report, modifications, assessment permission
and private photo references. It does not represent diagnosis or custody.

`GET /v1/maintenance/requests/{request_id}/photos/{photo_ref}` takes the same
organization query. It repeats the assignment check, verifies membership in
the saved request, and reads the attached bytes only under the full stored assignment and photo binding. Missing records and denied assignments return the same 404 response. An expired
session returns 401. An unavailable authority or invalid response returns 503.
References are private. The operation receipt remains scoped to its submitting actor.

## Unsubmitted photo retention

Service Operations records the first durable upload instant using database time. Unsubmitted bytes expire exactly seven days later. Exact retry uses
the original upload key and never extends retention. At or after expiry,
the service denies use of the reference. The expiry worker removes the bytes
in batches and resumes after restart. The remaining upload key prevents delayed
retries from restoring the bytes. A draft abandoned
before submission has the same expiry. An acknowledged request closure
makes its unsubmitted references unusable and eligible for earlier cleanup.
The service serializes expiry and closure with submission attachment. Attached
evidence follows the retention of the committed request.

A submitted receipt has revision 1. Denied, stale and pending results have
revision 0 and do not acknowledge a submitted request. Submission receipts
include the committed brand and intervention. Receipt
recovery matches these against the original command or a reviewed retry and
displays the scope from the matched receipt.

Submission locks the selected uploads in the same transaction and checks
their actor, watch, business, operation, brand, intervention, watch revision,
capability revision and policy revision. A changed scope requires new upload
operations under the same request reference. At most ten photos attach to a
request, with at most 100 preparations across scope reviews. It checks expiry with
database time after taking row locks. Cleanup and upload replay use the same
row locks, and closure uses the same operation lock as admission.

The request, attachments, receipt and outbox commit together. Failed attachment
rolls back admission. Exact committed replay returns the existing receipt.
Shared composition must register the expiry worker and image support.

An inactive destination or unsupported assessment returns
`409 destination_ineligible` on submission. Photo preparation returns the same
outcome if the business is no longer eligible for the watch. Operation lookup
and closure check the submitting actor's current permission to resolve their
original request independently of whether the destination can accept new work.

## Business assessment inbox

Submission atomically stores a private request and its delivery event. A bounded
worker delivers the event to the selected business's inbox using the original
event ID. The inbox receipt and outbox acknowledgement commit in one transaction.
An interrupted transaction leaves the event ready for retry. The inbox stores
only routing references and delivery time.

`GET /v1/maintenance/assessment-inbox?organization_id={organization_id}&offset=0`
returns up to 50 request references and the current scoped total. The
`assessment_queue_access(actor_id, organization_id)` provider operation supplies
the current actor and business binding, assignment revision and eligible request
IDs. The provider checks current membership, assigned assessment and evidence
permission. An explicit `routing_allowed: true` decision grants business staff
responsible for routing new work access to delivery references for that business
before individual assignment. The inbox response contains no watch, buyer or
evidence data. A literal false denies access. Missing or malformed facts leave
the inbox unavailable. Opening a report or photo requires a separate, current
request-specific assignment and evidence permission.
Runtime, gateway and assignment integration remain connected prerequisites.

Photo preparation binds the selected brand, intervention, watch revision,
capability revision and policy revision. The service checks these against
current context before storing bytes. Withdrawn scope returns
`destination_ineligible`. Changed revisions return `stale_photo_scope`.
Both responses let the buyer review current scope while keeping their draft.

Delivery reserves each attempt durably before writing the inbox. Interrupted
attempts count toward the eight-attempt limit. Reservations become eligible
again after one minute. Once the last reservation expires without delivery,
the event is held with the configured recovery operator. Composition supplies
`maintenance_delivery_operator_id` and a current
`delivery_recovery_access(actor_id)` decision. The operator lists assigned
holds at `GET /v1/maintenance/delivery-recovery`, reviews within 24 hours and
escalates after 48 hours. The worker records each due escalation with the
original event and hold time in the same transaction that marks the hold
escalated. The recovery queue presents escalations first and directs the
operator to resolve them. Requeue records any due escalation under the same hold lock before clearing
the current hold. Escalation history survives a requeue. After investigating, the operator can requeue via
`POST /v1/maintenance/delivery-recovery/{operation_id}` with the exact
`held_at` from the current hold. Requeue starts a new bounded cycle under the
original event and request IDs. The delivery worker transfers existing holds
to the configured successor in bounded batches, preserving the original hold
time and both deadlines. Each acknowledged requeue has a durable receipt
bound to its event, hold timestamp and operator. An exact replay under
current operator access succeeds even after a later hold has been requeued.
A stale retry without a receipt cannot reopen a newer hold.

Photo preparation returns a `PhotoReceipt` with revision 1. The receipt
echoes the exact upload and request operation IDs, actor, subject, business,
watch, brand, intervention and source revisions. The client verifies those
facts before keeping the photo reference. A mismatched response leaves the
original upload available for retry.

An operator can send `action: "acknowledge"` with the current hold timestamp
to record a first response without requeuing. Requeue also records a first
response if one is missing. The original response time and operator survive
retries, transfers and requeue. At the 24-hour deadline, a hold without a
response enters the overdue response queue. Escalation remains due at 48
hours if delivery has made no progress.

The first hold starts the 48-hour escalation clock for the delivery. Requeue
renews the attempt budget and its hold reference. The original deadline stays
active while those attempts run and across later holds. The deadline produces
one durable escalation, including when delivery succeeds at or after the
deadline before the worker has recorded it. Delivery before the deadline
satisfies the outstanding delivery and ends the escalation check.

An escalated delivery stays in the current recovery operator's queue while
its requeued attempts are outstanding. In this state, `retry_in_progress` is
true and `held_at` identifies the most recently requeued hold. The operator
can submit `action: "review_escalation"` with that reference. Review is
recorded once against the original escalation. It changes the next action
to monitoring and preserves the active reservation, attempt budget and
deadlines. A stale hold reference cannot record a review. After late
delivery, an unreviewed escalation stays in the queue with
`next_action: "review_delivered_escalation"` and `retry_in_progress: false`.
The operator uses the same hold reference to record the disposition. A
delivered item leaves the queue once its escalation has been reviewed.
Escalation and review history remain available for audit.

The recorded escalation review binds the original event, reviewing operator
and requeued hold timestamp. An exact replay by the still-authorized operator
acknowledges that review after delivery or a newer hold and leaves the current
delivery state intact. Earlier reviews stored without a hold reference remain
historical, with no exact replay binding inferred.

An existing exclusive watch commitment returns `409 watch_committed` for
new admission. Buyer access remains current. Keep the draft and original
operation reference, and retry after the commitment ends or resolve the
reference through lookup and closure. An exact committed replay still returns
its receipt under the current private access checks.

Admission returns `409 photo_unavailable` when an attachment cannot be
verified. Resolve the original receipt first. For a scoped missing receipt,
prepare fresh upload operations under the same request reference, using current
assessment scope and the original private draft.

## Received-case diagnosis

A received intake binds its own `case_id` to the acknowledged `request_id`.
`POST /v1/service-cases/{case_id}/diagnosis` records the independent assessed
finding and lines under the assigned business assessor. The `Diagnose` command
uses a stable operation ID, both case and request IDs, the watch, and the
expected diagnosis and assignment revisions. The command requires exact current
custody and the reviewed opening consent. The `DiagnosisReceipt` binds those
facts to the resulting assessment and its lines. A request acknowledgement or
text recorded as a symptom is never an assessment receipt.

`GET /internal/v1/service-cases/{case_id}/diagnosis/operations/{operation_id}`
recovers the assessed receipt under the original actor and current assignment.
`GET /internal/v1/service-cases/{case_id}/diagnosis` is a current Pricing/Orders
read. It rechecks receipt, watch, incident, intake and opening revisions before
returning an assessment as current. Pricing uses the case ID as its source ID,
not the maintenance request ID. An accepted quote selection is transported to
`POST /v1/case-lines/{request_id}/acceptance` with both identifiers.
