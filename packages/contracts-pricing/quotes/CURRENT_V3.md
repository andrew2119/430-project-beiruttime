# Current and retained USD economics v3

Replaces active v2 validation; source baseline 9e4da83, implementation in progress.
`GET /internal/v3/quotes/{id}/validation?buyer_id=...` authenticates the calling
Orders, Catalog, Eligibility or Service Operations service. Exact current source,
buyer, business, assessment, quote revision and selected scope are rechecked.
`expires_at: null` means **committed economics**, not unlimited payment authority.
Pricing grants no execution, payment, custody or review authority. The response's
`execution_authority` is always `not_granted`. Downstream consumers must check
current consent, identity/eligibility and permissions independently, without any
capacity scoring or wealth attestation.

Uncommitted watch/assessed previews last fifteen minutes. Active generic watch
previews use schedule usd-v2 and purpose bid/offer/purchase; job quotes must use
the assessed route with schedule usd-job-v2, never the old generic business_quote
watch-fee preview. Reissuing identical current terms reuses the unchanged accepted
quote/decision (or a still-live issued preview) without new customer acceptance. A winner and an admitted
accepted offer retain economics without a price deadline. Unchanged accepted job
quotes remain usable beyond the original preview expiry; a new scope/revision,
known withdrawn consent or revoked business blocks current validation without
rewriting the retained amounts. Historical non-USD records remain unchanged and
are excluded from active forms, validation and financial receipts. They require
recorded reconciliation; there is no conversion.

Orders calls `POST /internal/v3/quotes/{id}/commit` after a durable fixed-price
allocation with buyer_id, order_id, quote_revision, total_minor, committed_at.
The signed Orders caller attests actual serialized allocation time, which must
fall after review and before preview expiry. Retry exactly those fields; conflicts
never overwrite the first commitment. Delayed acknowledgment is allowed. This
attestation does not create an order. Orders owns the notified payment clock:
start it only after the required buyer notice is durably available, never from a
preview's expiry or Pricing's acceptance time.

`GET /internal/v3/quotes/{id}/retained` is Orders-only, read-only historical money.
It never grants allocation or execution. Consumers of old v2 validation must
upgrade explicitly; they fail closed with contract_upgrade_required.

Watch policy `usd-v2`, revision 2: 3% buyer surcharge and 5% seller commission.
Job policy `usd-job-v2`, revision 2: customer pays accepted base; business pays 5%
from that base and receives 95%. platform_fee_minor and seller_commission_minor
are aliases for the **same** job business fee; do not deduct or sum them twice.
All percentages round half up to one cent. All amounts are integer USD cents;
people type and see dollars. Every collection remains simulated.

Assessment and unrepaired-return charges require separate explicit acceptance.
Current and retained responses expose accepted_fee_lines.assessment and
accepted_fee_lines.return_transport. A positive disclosed return_fee_minor alone
is never permission to charge it.
Assessment, when accepted, is in the job base. Return transport is retained as a
conditional accepted line, not charged or included twice in the job total.
The quote records the non-refundable business-fee obligation: on a full job
refund the customer receives the permitted gross job amount, never gross minus
5%. The business still owes that 5%, collected once from its saved simulated
method when no payout can fund it. A receivable or unknown collection is not cash.
Orders owns collection, refunds, reconciliation and actual payment-readiness
proof. No fixture here asserts paid, inspected, received or completed state.

## Command recovery and page reads

The commitment body is `FixedPurchaseCommitV3` in both language contracts.
An identical retry returns the original committed result even after preview expiry.
A different buyer, order, revision, amount or allocation timestamp cannot replace it.
A lost response remains uncertain until the same command returns its retained result.
Current validation and retained history are separate reads with separate authority.
The private operation lookup is `GET /v1/pricing-operations/{key}` and binds both
actor and selected business; a missing result never implies success.

`GET /v1/quotes?page=1&page_size=30` returns `items`, `total`, `page` and
`page_size`. The maximum page size is 100. The server counts only the current
owner's USD records in the same statement as the page read. Ordering is newest
creation time then identifier. Invalid page bounds are refused.

`PlatformPaymentReadinessV3` is the Orders-produced job proof, bound to buyer,
order, watch, accepted quote revision, USD amount and payment operation/revision.
It has no capacity or wealth fields. Only `paid_held` with all exact bindings can
satisfy payment readiness; current scope, consent, allocation and permissions
remain independent execution prerequisites. Pending or absent facts never pass.
