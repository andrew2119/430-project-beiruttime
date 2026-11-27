# Current intake authority

Records, evidence and operation recovery use current assigned-record authority.
Before deployment, verify assignment, custody,
opening authority, protected photo processing and both entry points.
Assignment outages return unavailable. Current custody and opening authority
are required for diagnostic opening, and new photo uploads require a safe-photo
declaration and metadata removal.

The rebuilt editor and assigned-record routes are the intake entry points.
Verify the current assignment, custody and opening providers, runtime photo
processing and gateway forwarding together before deployment. An assignment
outage leaves the
queue and private records unavailable. The selected-business queue returns
`intake_contract: "current"` after current assignment authority confirms the
caller's scope, including a successful empty queue. Receipt lookup and closure
use the registered records endpoint with the original operation reference.
Photo processing uses Pillow from the Service Operations runtime requirements.

The assigned-record contract also applies to historical retries. Recovery binds
the acknowledged revision to the original order and checks current write
assignment. Connected acceptance requires current assignment, custody and
opening providers, runtime photo processing and page registration.

An assigned writer can record reported symptoms before custody or payment.
Use an empty assessed issue and leave fee and opening acknowledgements unset
until their current authority is verified. The extended models in
`intake_command.py` use the existing intake storage. Query parameters cannot
select a different authority contract. Retry unresolved writes with their
original operation reference.

A recorded v1 receipt preserves history but lacks current watch, incident and assigned-record bindings. It cannot authorize diagnostic opening. The current handlers therefore report `diagnosis_allowed: false` until the injected current-authority provider verifies the exact receipt, order, actor, business and assignment bindings and the intake records the matching opening acceptance. Missing provider facts withhold opening.

The current diagnostic predicate requires matching watch identity and revision, selected organization, current incident revision, an actual receipt at or before authoritative UTC now, current assigned-record permission, specific opening permission, accepted assessment fee and no-polish acknowledgement. Reported symptoms remain separate from assessed findings. Receipt equality is valid; a future receipt is not. Execution separately requires exact accepted scope, current custody and Orders-confirmed held payment bound to buyer, order, watch, quote revision, USD and total cents.

List, detail, create, save and evidence operations require current selected-business authorization and assigned-record permission. Missing or invalid assignment facts return unavailable. Detail, existing-record save, evidence listing, upload and download return the same 404 for an absent resource or a denied record assignment. Session expiry returns 401 and unavailable assignment facts return 503. Stored authorship is audit history. Diagnostic opening always requires current opening authority. The active queue and its total include only USD records. Assigned staff can access historical non-USD records by record reference under the same current read checks. Those records retain their original values and remain read-only pending explicit reissue.

Connected verification requires the current assignment and opening providers and
Pillow from the Service Operations runtime requirements. Verification covers
revocation, a current receipt with independent opening permission, declaration
validation, metadata removal and exact historical upload replay.

The local paid-readiness seam requires `order_kind: "job"`; missing kinds and watch-sale funds withhold execution. The current input has no versioned Orders paid-readiness operation. Its exact producer contract and connected positive/negative checks remain deferred; this local seam cannot authorize execution independently.

Execution requires both accepted and current scope revisions to be positive integers. Missing, boolean, fractional or nonpositive revisions withhold execution even when other prerequisites match.

The opening authority response carries receipt-snapshot watch and incident fields and separate current watch and incident fields for the assigned order. The provider supplies the current fields from the current order/watch and incident records. A mismatch with the receipt snapshot withholds opening while retaining the historical receipt. Execution requires literal affirmative custody and a complete job payment readiness response, including the payment operation and its positive revision.

A scoped save may replace an acknowledged custody receipt with a newer current receipt verified by Orders for the same order and business. Clearing or rolling back a recorded receipt is rejected. The previous receipt ID, receipt revision, intake revision and receipt instant remain in the private record history, outside the editable record, and the current receipt is written atomically with the intake revision, audit and event.

`GET /v1/intake/operations/{key}` resolves a committed save or evidence upload under the original actor and selected business, with current write permission on the associated order. The response carries `operation_id`, `organization_id`, `record_id`, `revision` and `kind` (`save` or `evidence`). The lookup uses the same transaction lock as admission. A missing receipt or unavailable lookup leaves the original operation available for another check. Drafts and file content are excluded.

Direct save and evidence acknowledgements echo the operation key and selected
organization. Saves also echo the order reference. Evidence acknowledgements
carry the attachment ID and its record ID. Exact replays include these
bindings even for receipts stored before the fields were added. Clients keep
the operation unresolved until the acknowledgement matches these bindings,
the target record when known, and the exact next revision. Receipt recovery
uses the same expected result revision, retained with the operation key even
when an access change clears the private draft.

The assignment client uses signed Service Operations authority for
`GET /internal/v1/intake-readable-orders?actor_id={actor_id}&organization_id={organization_id}` (RecordListAccess)
and `GET /internal/v1/intake-record-access?actor_id={actor_id}&organization_id={organization_id}&order_id={order_id}&permission={permission}`
(RecordAccess). Service Operations resolves the caller before sending the bound actor and selected organization; Orders rechecks their current assignment. Unavailable or malformed responses withhold access.

`DELETE /v1/intake/operations/{key}` resolves an uncertain write under the same
admission lock. A committed operation returns its scoped receipt. For an absent
operation, it records a durable closed key for this actor and business, and returns
`operation_id`, `organization_id` and `state: closed`. Delayed writes with that key
cannot commit.

Diagnostic opening also requires the saved private `opening_acceptance` to
match the provider's current quote ID, quote revision, accepted terms revision
and consent revision exactly. Equal fees alone cannot carry acknowledgements
across terms. An assigned staff member can review the current provider-backed
binding and fee on the detail response, then explicitly record them in a
revision-checked save. Records without this optional binding retain their
history and withhold opening. A save without the binding keeps its original
request digest for exact retry.

Only the intake service returns `404 operation_missing` when the scoped
lookup finds no committed receipt. A generic route failure leaves the
operation unresolved. The browser uses the existing registered
`POST /v1/intake/records` with `{action, operation_id}` and the selected
organization. The `lookup` and `close` actions apply the same permissions and
operation lock as the dedicated routes. A receipt or closure returns 200.
The recovery command contains no draft data and accepts no intake fields.

The positive intake scenario needs a current assignment fixture for list, read,
and write. A save can confirm opening when it records a new acknowledgement set verified
against current custody and opening authority in the same transaction. A replay
withholds opening. A separate detail read rechecks the saved acceptance and
current custody.

Current assignments must come from a composed current-authority provider or the
Orders assignment service. Private operations withhold access when neither can
confirm a current assignment.

A new or updated received record requires current custody under the intake write
transaction. The signed Service Operations request to Orders is
`GET /internal/v1/intake-current-custody?actor_id={actor_id}&organization_id={organization_id}&order_id={order_id}&receipt_id={receipt_id}`.
A 200 must carry a valid `CurrentCustodyReceipt`. A 409 means custody is
unconfirmed, 401 and 403 preserve access errors, and a missing endpoint or
other failed response is unavailable. Composition may supply
`current_custody(actor_id, organization_id, order_id, receipt_id)` using the
same response contract. `CurrentCustodyReceipt` binds the receipt
and actor to both the receipt snapshot and the current watch and incident
revisions. The provider confirms actual receipt and current custody without
requiring permission to open the watch. It denies invalidated receipts and
fences the current custody facts through admission. A denied, mismatched,
future or unavailable receipt cannot produce a received write or event.
The same current check governs the custody status shown on detail. A legacy
receipt alone does not convey current custody.

For an assessment order, the signed opening source binds `maintenance_request_id`
and `reservation_input_watch_revision`. Before adding the association, the intake
transaction verifies the exact maintenance submission acknowledgement and Orders
assessment-fee commitment. The received record and its receipt return the
`maintenance_request_id`; the intake `id` is the separate case identifier used
by diagnosis and Pricing. These identifiers are never interchangeable. Linking
preserves the original intake event shape and does not set a diagnosis.

Changing or clearing assessed findings requires a current custody receipt and
an explicit assigned technical assessor grant. The record access operation
takes `permission: "assess"` for that grant. The provider checks current
appointment to the technical assessment role for this order and organization.
An ordinary intake write grant covers reported symptoms and receipt recording.
An unchanged historical finding can accompany those writes. The assessment
grant covers recording observations. Diagnostic opening still requires the
separate opening authority and customer acknowledgement checks.

Composition can supply a dedicated `intake_assignments` adapter with
`record_access(actor, organization, order, permission)` and
`readable_orders(actor, organization)`. It uses the same validated assignment
responses as the Orders transport. A current write assignment admits a
preparatory record without a custody or payment provider when no receipt or
assessment is being recorded. A current read assignment exposes that record.
Fixtures must explicitly grant both scopes and leave assessed findings empty.
On an assigned preparatory creation without verified custody, the legacy
unassessed placeholders are stored as an empty finding. Any other finding still
requires the current custody binding and a technical assessor grant.

The business intake page and Service Operations use the current contract.
Missing assignment facts return unavailable. Connected operation requires
current assignment, custody and opening authority and the Service Operations
runtime photo dependency.

Exercise both the queue and the order-specific read and write checks with
the assignment producer or a contract-matching test transport. Send an empty `assessed_issue` for a preparatory intake.
Use the awaiting-intake state to display that assessment has yet to start.
Supply current custody separately when recording receipt, then verify opening
through the detail read with the exact current customer acceptance binding.
For the earlier evidence scenario, send a safe-photo declaration and verify the
decoded image and removed source metadata after download.

Opening authority and current custody must agree on the receipt, watch identity,
watch revision, incident revision and receipt instant. A disagreement withholds
the opening decision and the offer to record acknowledgements.

A new or changed acknowledgement set or nonzero fee is admitted only with
matching current authority in the write transaction. The quote, terms, consent,
fee and all three acknowledgement flags must match. Clearing the entire set
is permitted. Unchanged historical values can accompany unrelated edits and
remain historical until the current checks confirm them.

Active findings bind the assessed watch, watch revision, receipt, receipt
revision and incident revision. Detail exposes findings only for matching
current custody. Superseded and unbound findings are retained in private
history. Replacing custody clears unchanged findings from the active record.
An assigned assessor can then record findings for the current receipt.

An assigned assessor's detail response includes `current_assessment_custody`
while custody is current. Adding, changing or clearing active findings requires
sending that exact binding as `reviewed_assessment_custody`. Admission compares
the reviewed watch and receipt IDs and the watch, receipt and incident revisions
with current custody under the record lock. A mismatch returns
`409 stale_assessment_custody` even if the intake revision has not changed. An
ordinary intake save can still carry unchanged findings without this field.
The field is covered by the operation digest when supplied and is omitted from
the digest when absent, preserving exact retries of earlier saves.

The assignment transport can run alongside a custody and opening adapter.
The dedicated assignment adapter takes precedence when configured. Otherwise,
a combined adapter supplies the assignment operations it implements, and the
Orders assignment transport supplies the others. A refusal or unavailable
response from the selected source never falls through to a different source.

Before connected acceptance, verify the Orders assignment producer and the
existing intake scenarios together. A missing Orders assignment route
returns 503, including for a preparatory intake. The service distinguishes
this from expired identity or an explicit
assignment denial. The preparatory intake needs only the current write
assignment when it records reported symptoms without custody, assessment or
fee acknowledgements.

Connected intake requires the deployed assignment transport and verification
of the existing intake scenarios against these current facts. The local HTTP
scenario exercises missing, malformed, revoked and restored assignments
against one operation key. An unavailable or denied assignment leaves the
order slot free. A restored write assignment allows that same operation to
create an awaiting-intake record before custody or payment.

A detail read can offer `receipt_revision_for_review` when the current provider
verifies a newer revision of the recorded receipt. To check a different receipt,
use `GET /v1/intake/records/{id}?organization_id={id}&review_receipt_id={uuid}`.
This requires current read and write assignment and returns the intake
`revision` and a `receipt_revision_for_review` for the verified replacement.
Offers carry receipt ID and revision, watch ID and revision, and incident
revision. They confer no received status or opening permission. Staff explicitly
review those facts and echo them as `reviewed_receipt_revision`. The write
rechecks the exact custody binding under the record lock and rejects stale
review for either a replacement receipt or an advance of the recorded receipt.
The original receipt revision remains in history.

A fresh save may confirm opening after verifying current facts. The operation
receipt records the saved revision without an opening decision. Replaying a
save confirms that revision and withholds opening. Request detail to verify
opening again. The assigned intake scenario exercises an awaiting
intake with current assignment and verifies opening on detail with current
custody authority and matching customer acceptance. The missing-assignment scenario verifies an unavailable result before any
record is written.
