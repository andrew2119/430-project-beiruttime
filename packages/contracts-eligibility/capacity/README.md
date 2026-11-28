# Exact payment readiness v1

The historical capacity task now reads exact simulated platform payment readiness.
It requests no financial history or identity evidence. Tracker references remain
BT-361, BT-362, BT-363 and BT-364 (parent BT-71).

Operation lookup: `eligibility.capacity.read.v1` is a private, read-only operation.
The caller supplies a stable operation reference and current expected context.
This read reference is correlation only, not a command receipt or mutation key.
Repeated reads always evaluate the supplied context afresh; they never replay a
stored paid result, including when the caller changes a binding under that reference.
Only an authenticated Orders adapter may supply the payment fact; a client,
projection or cached answer cannot supply it. Provider reads are bounded by one
second. Retry an uncertain read with the same operation reference. No payment,
allocation, identity decision, grant, approval or execution permission is issued.

The expected context binds actor, business, subject, watch, buyer, job order,
accepted quote and revision, request revision, authority revision, USD total and
current payment revision. Current authority must be rechecked for every read,
including duplicate reads. Missing authority or missing/unknown source facts stay
pending; explicit revocation, mismatched bindings and stale revisions deny.
Only exact `paid_held` becomes `paid`; exact `unpaid` stays `unpaid`.
No identity verdict is inferred from any payment state.
Denied or pending results may echo unverified input bindings for private
correction; they are never retained payment facts. Paid and unpaid results
require the valid input schema.

The local adapter boundary and synthetic fixtures are development contracts.
Connected C13 and O03 operations, authenticated HTTP integration, durable operation
lookup and restart proof remain deferred. Runtime registration belongs to its
separate owner. This module has no journal, balance, event publisher or mutation.

## Pending support responsibility

Before calling the read, the trusted adapter must durably obtain one support
assignment under the stable operation reference, bound to its private case scope.
`support.schema.json` describes that retained assignment; it is not customer input.
Missing or invalid assignments prevent the read from returning a readiness result.
Retries and process restarts must reload the same assignment, never create a new
opening time. Reassignment preserves the opening and recorded progress times.
The assigned operator is `next_actor` for every pending result, including authority
uncertainty, missing facts, malformed responses and timeouts. `next_action` is
available in English and Arabic. `next_review_at` is the original opening time plus
24 hours. `escalate_at` is the last recorded substantive progress time plus 48 hours;
initial progress equals opening. A read or retry is not progress. Elapsed deadlines
remain visible and overdue until support acts; they never turn pending money into
paid, unpaid, released or authorized work. Only recorded substantive support work
may advance the progress timestamp; the first-response deadline never moves.
The support owner must schedule first response and escalation from these retained
timestamps, including after restart. Durable assignment, scheduling and escalation
execution require connected integration and remain deferred with C13 and O03.
