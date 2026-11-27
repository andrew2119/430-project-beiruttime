# Listing withdrawal and no-bid cancellation

Catalog retains the original actor, organization, listing, watch, revision, reason
and operation reference before any remote command. Pending listings are unavailable.
Retries and lost responses reuse that reference and immutable payload after restart.
Current identity and record scope are checked on every read and write.

Fixed-price and offers withdrawals use Orders commitment v2 and its serialized
physical-watch fence. A final response must identify the exact watch and listing;
success must identify the withdrawal source and withdrawn state. An unavailable,
malformed or unbound reply stays pending. No timer restores availability.

Auction listings use the proposed authenticated
`POST /internal/v1/listing-cancellations` boundary with `Cancellation` and
`CancellationResult`. The stable header key is `withdraw:{operation_id}`.
The provider must hold the canonical auction admission lock across the no-bid
check and guarded commitment transition, retaining the exact result atomically.
An admitted first bid or any sale commitment denies ordinary cancellation.
Auction scheduling, mode mutation, first-bid admission and callback reconciliation
remain with that provider. Catalog never opens, releases or duplicates its lock.
The provider must recheck current authority, source revision and watch identity.
A success means public availability is withdrawn, with all auction and private
transaction history retained. A denial links to the seller's auction exception route.

The scoped local lookup is `GET /v1/me/withdrawals/{operation_id}`. Unknown
references return unavailable, never success. Actor and organization must match.
Deterministic fixtures exercise success, denial, stale revision and lost response.
These are development fixtures. The cancellation endpoint is not yet connected;
provider serialization, restart, callback and race acceptance remain deferred.

Result revisions describe the listing source: success is exactly expected revision
plus one; denied and pending results cannot precede expected revision. A stale
source denial reports the current source revision. Other revision combinations
remain pending locally. The validated receipt is retained intact in the operation
outcome, including the source binding and result revision.

A stale denial, or any denial reporting a newer source revision, never restores public availability or rewinds the listing revision.
Reload retains that denial and its original operation reference. A fresh operation
is permitted only after authoritative source reconciliation supplies published
availability at a revision at least as new as the denied receipt and newer than
the original request. Historical operations remain individually replayable.
Source reconciliation is not supplied by a denial receipt; connected proof of
that recovery remains deferred until the source authority is connected.

Every result carries bounded English and Arabic explanations and a code with its
next action. Denials identify a bid, sale commitment or stale revision. Pending
receipts require reconciliation, an operator, a review instant and same-operation
retry. Pending receipts are durably retained without restoring availability.
Local interleaving models cover first bid, reservation and callback contenders in
both admission orders; they do not establish actual provider serialization.

Orders denial settlement additionally requires a `binding` object equal to the
immutable retained commitment payload plus `actor_id` and `organization_id` from
the local operation. All fields, values and types must match, including the
operation key, source reference, watch, listing, both revisions, kind and reason.
The watch's current `source_id` alone is not a denial receipt: it may name the
competing reservation. Missing or conflicting bindings leave the operation pending
and public availability held. The current Orders denial interface does not supply
this binding; connected denial settlement remains deferred until it does.

History uses `GET /v1/me/withdrawals?page=1&page_size=25`, with pages from 1 to
1000000 and page sizes from 1 to 100. It returns `items`, `total`, `page` and
`page_size`. Count and items share one database statement snapshot and current
actor, organization and listing ownership scope. Ordering is creation time then
operation reference, descending. Every page preserves the original recovery key,
reason and source revision; changing page or language never creates an operation.

Before accepting a new withdrawal, composition must supply
`withdrawal_operator_id`, the UUID of the responsible operator. Missing or invalid
assignment refuses the request before availability changes or remote work.
Pending operations retain a `recovery` record in their durable outcome, containing
that operator, `reconcile_same_operation`, first response due at original creation
plus 24 hours, and escalation at original creation plus 48 hours with
`escalate_to_supervisor`. Every timeout and malformed reply retains this record.
Retries, reloads and settlement preserve the assignment and deadlines; they never
restart either clock. Existing pending operations acquire the record on retry,
using their original creation instant. Composition must supply a current operator
for these older records before retry can contact a provider. Operator assignment,
response processing and escalation delivery require connected verification;
storing the deadlines does not claim that a response or escalation was delivered.
