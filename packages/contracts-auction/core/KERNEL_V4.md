# Canonical auction transaction v4

`kernel_v4.py` defines strict command and private receipt envelopes and
`current_state(lot, now)` with bounded cents and a public-field whitelist. The module
`kernel-v2/canonical.py` publishes `execute(tx, command, authorize)` and
`lookup(tx, command, authorize)` for service-local composition. These functions
borrow an active transaction, never commit, and make no dependency requests.
The runtime adapter must integrate this interface before connected acceptance.

Lock order is operation advisory lock, then auction advisory lock, then auction
row lock. Admission, cancellation and close share the `auction:` lock namespace.
Time is sampled from the database after acquiring that lock. The original
scheduled end is authoritative, including equality. No extension is supported.

The current-authority callback must deny missing records, revoked membership,
wrong business/watch/owner and stale policy. Cancel requires the current seller;
close requires internal close authority. Confirm cancellation additionally
requires the retained cancellation reference and confirmed commitment release;
an unknown release remains pending. The callback reads local authoritative
records in the same transaction; dependency preparation must happen beforehand
with bounded calls and immutable retained references. A callback exception rolls
back the entire caller transaction. Never substitute a cache or caller flag.

Cancel before close with zero accepted bids and no first-bid fence enters
`cancellation_pending`. This fences admission while release reconciles. Only
confirmed release permits `cancelled`, including when confirmation arrives after
the scheduled end. A first-bid or listing-edit fence denies ordinary cancellation.
After any accepted bid cancellation is denied. Lock acquisition decides a race;
no separate count or unlocked projection authorizes cancellation.

At the fixed end, no bids or a public price below reserve means no sale. An unused
ceiling never meets reserve. A qualifying public leader records a fixed winner;
allocation is a separate pending operation, never inferred from this receipt.
Legacy purchase pending/reserved becomes `ended_legacy_review` without releasing
money, changing a winner or reopening bidding. Its financial resolution remains
with the commitment owner. `resolve_legacy_no_sale` requires that owner's retained
known no-attempt refusal and confirmed release, checked by the current-authority
callback in the same transaction. Unknown or held money must deny this action.
Resolution records no sale and never reopens bidding. New auction purchases are excluded.

Each operation retains its exact command and receipt atomically with the mode
change. Changed bindings under the same reference conflict. A stale revision
retains a denial; retrying its reference returns that same denial. A lost response
uses lookup with the original command and current authority. Missing operations
are unavailable, never created by lookup. A new deliberate action uses a new
reference and reviewed revision. Pending is not success.

The operation table is also the durable local delivery queue: `delivered_at` stays
null until the consumer records its inbox receipt. Delivery retries use the same
operation ID. No consumer is wired by this change. Delivery and allocation proof,
including timeout/restart and duplicate handling, remain deferred until wiring.
No private ceiling, reserve, evidence or winner identity enters this queue.

Recovery text keys have complete English and Arabic mappings in the deterministic
fixtures. Codes are machine values, not customer-facing fallback text.

The authority callback returns the assigned responsible person's ID. Pending
cancellation, legacy review and allocation retain a reason, responsible person
and first follow-up within 24 hours. Missing responsibility fails closed and
rolls back. Support escalates after 48 hours without progress; the delivery
consumer owns that scheduled escalation. `current_state` requires the matching
retained receipt for those modes and exposes that follow-up, failing unavailable
if it is missing. Winner-recording success means only canonical result recording;
`allocation_pending` never proves an order or payment exists.

Only an explicit `USD` currency permits active state or canonical mode changes.
Missing or other currencies retain the lot unchanged and record
`currency_reconciliation_required` with a responsible person and review time.
Retries and lookup retain that same private receipt. No winner, allocation or
release is authorized by it. Active `current_state` reads fail unavailable before
exposing amounts; historic economics remain restricted and unchanged pending
recorded reconciliation by their owner. Currency is never defaulted or converted.

The public no-bid price may be zero cents. Before recording a closing result,
retained opening, current and reserve amounts must be bounded integer cents.
Invalid retained economics leave the lot unchanged and the result unavailable.
