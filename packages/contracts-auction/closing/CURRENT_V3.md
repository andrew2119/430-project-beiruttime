# Close result v3

The canonical Auction lock serializes the close against admitted bids and mode changes. The scheduled UTC end is inclusive for closing and exclusive for bids. Only the final public price meets reserve; an unused ceiling never does.

`POST /internal/v3/auctions/{auction_id}/close` accepts `expected_end_version` and authenticates the Auction service. `GET /internal/v3/auctions/{auction_id}/close-result` is the authenticated operation lookup for Auction, Orders, Pricing and Communications. Both return `CloseResultV3`; an absent decision returns 404. Retry the original auction reference. A different request reference never creates another result.

`operation_id` identifies the immutable decision. `revision` starts at one and advances only when allocation reaches a verified terminal result. `allocation_operation` is `close:{auction_id}` for the fixed winner and never changes on retry. Pending allocation keeps that winner, quote and allocation payload. Denied allocation requires operator reconciliation and never promotes another bidder. A legacy purchase hold ends temporally with no new winner and no financial release.

Stale end versions deny before any new decision. An existing decision is returned unchanged even for a stale delivery. Missing authority, malformed responses and unavailable dependencies never imply successful allocation. Lease tokens and expiry fence writes; Orders owns allocation idempotency and current buyer, stock and quote authorization. Orders alone commits retained economics and emits the payment notice intent. No notice receipt means no payment clock.

Public and own-result v1/v2 remain compatible. The internal v3 lookup contains masked winner text and no private ceilings or evidence. It is a recovery record, never permission to charge or release.

Held results retain `responsible_operator_id`, `next_action`, `response_due_at` (24 hours after creation), `escalation_due_at` (48 hours), and `escalated_at`. The internal recovery lookup exposes these bindings. A retry, denial or unavailable allocation never restarts either deadline or changes the responsible person. The worker records overdue escalation and its notice intent atomically once; it never releases money or changes the winner. Successful allocation clears the follow-up action.

The composition supplies `app.state.closing_operator_id` from a current, authorized operator assignment. Missing or invalid assignment persists the close decision with `assignment_required:true`, a null responsible person and the original follow-up deadlines. Assignment availability never prevents the scheduled end or changes the winner. Existing unresolved records retain their original deadlines and are assigned on the next scoped close delivery; overdue unassigned records also emit an assignment-required escalation. Current assignment-provider authorization and notice delivery require connected verification. Escalation timestamps are follow-up metadata and do not advance the commercial result revision.

Each close delivery and allocation recovery is isolated from failures in other records. Failed work remains eligible for a bounded later retry; cancellation still stops the worker.

Every worker poll also retries assignment for up to ten existing unassigned held results, oldest first, under row locks. This includes pending allocation, denied allocation and legacy review. Assignment recovery preserves the original decision, operation, result revision and follow-up deadlines; unavailable assignment remains eligible for the next poll.

Close delivery claims at most ten due records per poll and durably schedules their next attempt 30 seconds later before processing. Previously unattempted records precede retries; eligible retries run oldest first. A failed batch or process restart therefore leaves later due records eligible without changing any decision or allocation reference.
