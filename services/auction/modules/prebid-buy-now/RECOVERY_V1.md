# Historical recovery version 1

New auction purchases are refused. Exact historic receipts remain readable.
This private additive interface does not register a purchase or payment route.

`Binding` is the immutable operation lookup request. The operation identifier,
subject, watch, actor, business and expected revision must match on every retry.
`Resolution` is the strict Orders lookup response. Missing, malformed, stale or
mismatched responses are unavailable. A reservation denial is never proof of
no attempt. Only explicit `no_attempt` distinguishes known absence from unknown
funds. Only Orders can report `released`; that report does not reopen an auction.
Declined, pending and unknown outcomes never establish collected funds.
Only `paid_held` reports confirmed held funds; all six provider states remain
distinct in the recovery read. No local classification releases a commitment.
The durable provider receipt retains the original quote and policy binding;
this interface cannot replace accepted economics or authorize a new charge.

`cancel_no_bid_v1(transaction, Cancellation)` is the canonical cancellation
operation. It serializes current authority, source revision, zero accepted bids,
fixed scheduled end and exclusive-commitment checks under the Auction lock.
It writes its receipt and event intent atomically. Its operation lookup returns
the same retained result for an identical retry and denies conflicting reuse.
Denied and stale results never mutate auction mode. Lost responses remain
pending and retry the same reference. Cancellation at or after scheduled end
must retain a closed auction; no runner-up, relist or schedule extension occurs.
The consumer never substitutes a local transition for this operation.

These interfaces are development contracts. Runtime composition, authenticated
Orders lookup, canonical cancellation, database atomicity and connected
recovery remain pending provider integration. Local fixtures prove consumer
behavior only. Every held case needs a responsible operator, a next action and
follow-up within 24 hours, with escalation after 48 hours without progress.

The private `GET /v3/prebid-operations/{operation_key}` read checks the current
individual buyer and reads only that buyer's receipt. It returns the retained
historic snapshot and a separate attempt-aware resolution with English and
Arabic next-action text. Missing retained policy/quote revisions or an absent
Orders reader return unavailable without guessing those revisions. Both calls
have a one-second bound. Cancellation responses must match the complete binding
and a non-stale revision; malformed results remain unavailable. Quote fields are
explicitly null for a cancellation with no accepted quote. Policy revision is
always required. No public event contains these private bindings.

The read returns `resolution` and a `recovery` object containing the validated
provider state, revision, pending reason, responsible person (`next_actor`) and
follow-up deadline (`next_review_at`). Unavailable results return null recovery
details rather than stale or unvalidated assignments. English and Arabic
next-action messages distinguish declined, pending and unknown outcomes from
confirmed held funds. Provider assignment, deadline enforcement and escalation
remain connected acceptance obligations; displaying them is not proof of completion.
