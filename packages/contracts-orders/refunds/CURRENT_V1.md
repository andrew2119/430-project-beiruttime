# Refunds v1

All operations and facts are private. No evidence bytes, notes, document references or public event payloads enter this interface. Errors expose a bounded code only. Money is integer USD cents; views accept and show dollars. All payment effects are simulated.

## Operations

- `POST /internal/v1/refunds`: immutable `Command`, stable `operation_id`; returns `Operation` only after the Orders journal commits its receipt, reservation and outbox together.
- `GET /internal/v1/refunds/{operation_id}`: current operation lookup with current actor, organization, assignment and record scope. Unknown returns absent, never confirmed. Revocation denies even an identical retry.
- The journal owns settlement of the same reservation. Pending and unknown retain the full amount. Only a final decline may free it. Confirmation moves the amount from unresolved to confirmed without increasing the sum. Callback inbox receipt, revision and journal effect commit together. Conflicting duplicate callbacks deny; identical callbacks return the retained result.

These are additive interfaces for composition by the Orders runtime owner. They are not registered routes. `v1.py` is the strict source schema. `index.ts` is the view schema. Deterministic examples live in `fixtures.json` and contain synthetic values only.

## Transaction boundary

`Journal.refund_transaction(command)` serializes on the canonical order, including every refund entry point, payout, held payment and source change. The transaction must be bounded and fail closed if current facts cannot be established. It supplies current authoritative UTC time through the composed clock, current identity/business/assignment, quote, basis, source revision and journal totals. Facts must not be fetched from a projection. Scope checks precede private operation reads. `prior` compares the complete immutable command and returns the latest result; operation identifiers are globally unique, conflicting content denies without disclosing the earlier command.

`reserve(plan)` rechecks the fenced facts, creates exactly one reservation and operation receipt, increments the canonical revision and adds exactly one simulated refund outbox item atomically. It sends only the retained buyer recipient and principal; caller-controlled recipients and fees are forbidden. It must never return confirmed merely because a basis was approved. The journal's own authoritative totals serialize confirmed plus unresolved against `cap_minor`; this module creates no balances, allocation, journal or independent reservation table. External delivery uses the operation identifier as the stable retry key, with bounded attempts and a durable reconciliation next action. A timeout at any stage requires lookup or retry of the exact same command. Acknowledged reservations survive process restart.

`lookup` rechecks current identity, membership, assignment and record/watch scope before returning an operation, including after revocation or reassignment. The runtime authenticates internal consumers; body actor identifiers are never authentication. Body size is capped at 8 KiB before schema parsing. No files or arbitrary strings are accepted. Dependency deadlines are included within the adapter's two-second bound.

## Economics and basis

The cap is the minimum of confirmed refundable paid principal, retained principal and approved refundable basis. Buyer fees, inspection, transport, collected commissions and other fees are excluded from paid principal. Existing confirmed and unresolved refunds reserve the same cap. Refund permission must expire strictly after the authoritative instant: equality is expired. Failed private authentication needs neither buyer receipt nor a pass, and never permits seller release. Other post-transfer refunds require actual controlled return or a recorded failure exception; physical-return permission alone is insufficient.

A partial job basis permits only accepted unperformed labor and unused returnable parts at retained amounts. Consumed parts, completed work, assessment and transport are excluded by default. A reasoned dispute can instead approve a job-principal allocation.

Full job refund returns the gross permitted principal, without subtracting the business fee. The journal retains the existing business fee receivable once using the order/quote key; it must not create another receivable for each partial refund. When no payout remains to deduct it, the existing collection operation uses that key and saved simulated method. Unknown collection never means paid and never schedules another customer refund. This plan is a reference to the retained receivable, not recognition of collected cash.

## Failure codes

`denied`: obtain current scoped permission. `stale`: reload current decision and explicitly review a new request. `basis_required` / `return_required`: resolve the basis or controlled return. `cap_exceeded`: reload the remaining refundable principal. `pending`: lookup/retry the exact reference. `unavailable`: retry the read; do not infer success. Conflicting stable references deny as `conflict`. A view may offer a new command after a definitive refusal only when the adapter supplies an authoritative no-effect guarantee, no earlier result was uncertain, and a fresh scoped basis has been loaded. An absent lookup alone is not that guarantee; permission loss during reconciliation never discards the reservation reference.
