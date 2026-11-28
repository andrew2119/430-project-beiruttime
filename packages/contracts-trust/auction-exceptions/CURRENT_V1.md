# Exceptional auction actions v1

Private operation lookup: `GET /internal/v1/auction-exceptions/operations/{operation_id}`.
Command: `POST /internal/v1/auction-exceptions` with the exact Command fields in current.py.
The authenticated actor is server-derived. Body identity never grants authority.

The response contains schema_version, operation_id, subject_id, watch_id, actor_id,
organization_id, expected_revision, state, revision, pending_reason, next_actor,
next_review_at, next_action, escalation_at, quote_id, quote_revision,
policy_revision, assignment_revision and code. States are pending, acknowledged and denied.
Only an acknowledged canonical receipt confirms application. Revision is the current
producer revision, never an increment invented by this module.

Every command and lookup rechecks current identity, organization, assignment,
record permission and independent operator status. Seller end requires the seller
and zero admitted bids under the canonical lock. Any exceptional operator must be
independent of seller and affected bidder. Ordinary ceiling lowering/removal is denied.
Reasons are required; private reasons never enter public events, previews or logs.
No evidence uploads are accepted by this interface.

The Auction provider executes or prepares under its serialized lock, checks all
bindings, current revision and authoritative UTC close time. Before close, removal
or retraction recomputes current competition using the private v2 engine and records
history and required outbid notices atomically. This consumer never computes bids.
At or after close, Auction returns an immutable Orders exception intent with order,
watch, retained economics, source revision and operation bindings. Orders coordinates
payment, custody and commitment under its own authority. Never rewrite a winner,
create a runner-up or release uncertain money/stock. A paid cancellation pauses
fulfilment; refund excludes collected fees and custody transfer requires a controlled
return or recorded failure exception. No local balances or allocation are owned here.

Dependencies accept the same immutable operation reference, provide durable lookup,
use authenticated calls bounded to 1.2 seconds and return only private safe receipts.
A lost response is pending; retry the exact reference. A changed payload conflicts.
Revocation denies current reads even when the operation was acknowledged earlier.
Every pending result identifies a responsible operator, next action, 24-hour review
and 48-hour escalation. Acknowledged receipts survive restart.

Runtime registration, database deployment and provider connections belong to their
respective composition owners. The local repository is a private durable receipt
store; it must be located on restricted persistent storage, never a public cache.

A bound denied/stale_revision receipt carries the actual current revision even
when it is lower than expected_revision. Other lower-revision results remain
uncertain. Reason length is 10–2000 Unicode code points after whitespace stripping.
Definitive validation and permission rejections must be distinguished from transport
uncertainty; only definitive rejection permits correction with a fresh reference.
