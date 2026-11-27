# Current assessed case lines v1

Line kinds are extensible identifiers. Reported symptoms never create assessed work. Each assessed line binds an assessment revision, required/optional choice and exact integer USD cents. Duplicate or unknown selected lines deny. Every required line must be explicitly accepted; omission is not consent. A changed request or scope invalidates current acceptance while retaining the historic snapshot.

The operation table defines current scope, acceptance and operation lookup for composition. Receipts bind operation, actor, subject, selected business, watch, request, source revision, retained quote and policy. Denied and stale results never advance a revision. Uncertain acceptance remains pending with the original reference. Success, denied, stale and lost-response fixtures are deterministic transport examples, not seeded accepted work.

Current identity, business/assignment, the assessed source, accepted Pricing decision and record revision are checked on the relevant current reads and admission. An immutable operation receipt acknowledges only that earlier decision, not current execution permission. This transport owns no payment balance.

The registered transport persists a current accepted scope, immutable operation receipt and minimal outbox entry in PostgreSQL. `POST /v1/case-lines/{request_id}/acceptance` transports an already acknowledged Pricing repair-quote decision; it cannot grant independent consent. It requires the current personal buyer, exact case/request/watch/business/assessment/quote/policy revisions, unchanged diagnosed lines and explicit selection of every mandatory line. Unaccepted Pricing decisions refuse the operation. Current and operation reads require the owning buyer or current business record permission. Scope changes require a new revision and acknowledged decision.

Current scope rechecks the exact accepted Pricing decision and selected lines on every read. A superseded quote invalidates current scope. The original operation remains available as an immutable acknowledgement under its private scope.

The current read returns the `Scope` DTO. Its lines carry the line identifier, description, required flag, amount in USD and diagnosis assessment identifier and revision.

New acceptance acknowledgements include the case ID, assessment ID and assessment revision. Replay and lookup recover those fields from the retained command for earlier acknowledgements. The scope retains the selected line subtotal and the accepted Pricing payable separately. The payable includes the acknowledged assessment fee and must match the paid order before work can proceed.

Each line accepts integer USD minor units through 9,000,000,000,000, matching the assessed Pricing line limit.

After payment, the current scope read resolves the matching paid repair order from the caller’s Orders list. The lookup uses the caller’s bearer token and selected organization, if any. The Orders list is limited to the latest 100 visible orders and requires `orders.read` in an organization context. Pass the order ID as `repair_order_id` to read an older order or to use the existing case record permission without listing organization orders. The service checks the retained diagnosis acknowledgement and assessment-fee quote binding, plus the current repair reservation and exact paid amount. Before payment, omit the parameter to use current assessment opening authority.

A Pricing quote identifies one immutable buyer decision. A matching submission under a new operation ID returns the original acceptance and keeps its scope revision. Lookup can recover that acceptance through either operation reference. A different accepted quote and the current expected scope revision are required to advance the scope.

On acceptance and receipt lookup, the optional `organization_id` query binds the destination business. Acceptance requires it to match the command when present. The owning buyer submits and recovers the receipt under their personal identity, including when they belong to that business. Business staff still need current assigned record access to recover a receipt.

The acceptance transport uses the retained Pricing decision, not a second consent record. An accepted receipt names `accepted_terms_revision` (the exact Pricing quote revision) and `terms_digest`, which must match both the quote and the accepted Pricing decision. `GET /v1/case-lines/{request_id}/terms` checks the owner or assigned business record access and returns the bound `RetainedRepairTerms` from that authoritative version, including lead time, exact warranty and work restrictions, and separate assessment and return fees and acknowledgements. Policy changes or an unverifiable accepted snapshot cannot be represented as a current terms read. Older receipts recover the binding only from the exact retained Pricing decision; they do not infer terms from a policy number or fee.
