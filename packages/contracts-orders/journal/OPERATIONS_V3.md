# Simulated journal movements v3

The existing Orders journal remains the only journal. `Movement` is an immutable
request. The module exposes `reserve`, `lookup` and `settle` within the caller's
transaction. Callers never commit inside these functions. No HTTP route accepts a
policy result. Runtime composition must supply a current serialized policy reader;
absence returns unavailable. Reads and retries recheck current actor, organization,
record and source scope before returning private results.

The reader returns `CurrentAuthority`, bound to the complete request and retained
money. It locks current permissions, assignments, source revision, decision,
inspection/custody, recipient and holds until commit. It must not use projections.
Refund permission includes accepted unperformed lines or a reasoned decision and
actual return or recorded exception. Release permission includes current private
inspection or business assurance/job quality, actual receipt, elapsed accepted
window, and no dispute/incident. Equality ends the dispute window. Policy validity
ends at equality. All instants are authoritative UTC.

Reserve records pending intent and an outbox event atomically. The simulated result
uses a signed, exact request-bound callback. Pending never posts; confirmed posts
one balanced group and one event. Lost response retries use the same operation ID;
changed bindings conflict. A conclusive decline permits a new operation. Pending
refunds and releases reserve principal against the same retained maximum. Once a
release is pending no refund may race it. A pending refund prevents release.

Failed private authentication requires the current actual independent result and
accepted return line. Collection is commission plus return transport. Pending or
declined collection restricts new private publication and blocks return; it never
blocks otherwise permitted buyer principal refunds. Confirmed collection plus the
current custody instruction permits return. Job fee collection uses the retained
business fee, never customer principal. A full job refund is the permitted gross
job amount. A collection receivable is never reported as paid. Runtime policy and
publication/custody consumers must read the original operation through `lookup`.

Settlement and recovery always reconcile the original recipient and method. A
changed policy after reservation cannot redirect an existing transfer. Signed
confirmation still records money already moved; it does not grant fulfilment or
release authority. Every pending operation names a responsible actor and a next
review within 24 hours. Runtime scheduling and connected producer proof remain
required before activation.

Deterministic cases are in `fixtures/movements-v3.json`: success, denied, stale and
lost response. They are contract examples, never seeded confirmed transactions.


HTTP operation lookup: authenticated internal producers use
`POST /internal/v3/money-operations` and
`POST /internal/v3/money-operations/lookup` with the exact immutable `Movement`.
Signed simulated outcomes use `POST /callbacks/v3/simulated-movements` and the
`X-BT-Signature` header. Body streams are bounded to 8192 bytes. The policy reader
must independently establish the current acting subject from authoritative source
records and the authenticated producer's delegated scope; body actor identifiers
are bindings, never credentials. No end-user bearer is inferred from that body.

`permitted_refund_minor` is a cumulative permitted order allocation, not a fresh
allowance for every retry or operation. Pending and confirmed reservations consume
it together. Fee collection status must agree with this journal's confirmed money
operations. It is never supplied solely by a policy projection.

A late confirmation or newer pending outcome after a final decline records an immutable reconciliation
receipt and responsible follow-up, and blocks new money operations for the order.
The original declined operation is preserved. Such receipts require a separately
authorized resolution before further movement; no automatic correction is exposed.

Outgoing money binds a saved simulated recipient ID, owner, organization, revision,
route and exact opaque reference. The policy reader verifies its current ownership
and availability on initial reservation; an in-flight operation retains that exact
destination. Refunds also bind the original confirmed payment attempt and route,
checked against the existing held-payment journal. Recipient changes require a
separate operation only after a conclusive decline, never a rewritten pending one.

The additive migration is registered after the payment table migration. It extends
the original journal table to include movement postings, retaining the original
payment-only name as an updatable compatibility view for paid-read consumers.

The reader signature is `(transaction, request, authenticated_producer)`. Routes
pass the service identity returned by authentication, separately from the request.
Only the trust producer may request watch-sale movements; only service operations
may request job movements. A direct internal call without this context fails closed.

Release requests require `release_amounts`: `gross_minor`, `business_fee_minor`,
`buyer_fee_minor`, `shipping_minor`, `tax_minor` and `transfer_minor`. Gross equals
`amount_minor` and the sum of these deductions and the net transfer. Reservation
checks each component against retained economics and confirmed fee collection.
The exact immutable breakdown is included in the signed callback request and every
result; clearing posts precisely the signed `transfer_minor`. A 515000-cent sale
releases 475000 cents after 25000 business and 15000 buyer fee cents. A 500000-cent
job releases 475000 cents after the 25000-cent business fee. Already collected
business fees are not deducted again. Missing or changed breakdowns fail closed.
Every callback response, including an earlier event replay, overlays any durable
unresolved order reconciliation; immutable historical receipts remain unchanged.


Current money reads use authenticated `GET /internal/v3/orders/{order_id}/financial-readiness`.
The order lock covers the movement read. Its revision advances for each reservation,
advancing outcome and reconciliation receipt. `held_minor` excludes confirmed
outgoing principal and recognized buyer fees; `reserved_minor` includes pending
refunds and releases. `paid_held` readiness requires the original held payment and
no pending or confirmed outgoing movement or unresolved reconciliation. Older paid
fact routes return `financial_readiness_upgrade_required` after those movements,
never the original paid readiness. Historic order state remains a payment receipt,
not current financial permission. Current policy remains required for every action.

When cumulative confirmed watch refunds reach the retained watch-price maximum,
the same atomic refund posting recognizes the non-refundable buyer fee: debit held
funds for principal plus fee, credit clearing for principal and fee income for the
buyer fee. No seller transfer is needed. Partial refunds keep that fee held until
full refund or ordinary release. A full job refund recognizes no customer fee.
The separately confirmed business collection remains independent and once only.

Checkout reads current financial readiness inside its authorized order transaction.
`expired_fenced` remains pending while the original payment is unresolved.
`movement_status` distinguishes no outgoing movement, pending or confirmed refund,
pending or confirmed release, and reconciliation. Reconciliation takes precedence.
Confirmed partial refunds may leave held principal; a historical payment receipt
never proves that its original funds remain held. Missing readiness is unavailable.

Late checkout confirmation or uncertain outcome after decline, replacement or unpaid release records an
immutable reconciliation bound to the original attempt and callback. The original
attempt becomes held, including when the confirmation sequence is older than the
last decline. Replays retain the same receipt and current reconciliation status.
The hold blocks initiation, method changes and outgoing movements; unpaid expiry
retains any still-existing commitment. An already released commitment is never
recreated by the callback. No second paid posting or sale is inferred. The buyer
is recorded only as the recovery contact, never as the responsible operator.
Late-payment reconciliation requires a current order-specific operator assignment
from `l13_payment_recovery_assignments`, locked in the callback transaction. The
operator must differ from the buyer. The hold stores that operator and
`reconcile_original_payment` as its next action. Missing assignment returns
`recovery_assignment_unavailable` without acknowledging the callback; retry the same
signed event after assignment. Authorized assignment provisioning and connected
follow-up delivery remain required before activation.

Assignment is required before initiation and enforced for every payment attempt by
a validated foreign key. Assignment deletion is restricted while any attempt refers
to it. Before applying the additive migration to existing attempts, the authorized
migration session must supply `bt.payment_recovery_assignments` as a JSON array of
`{order_id,operator_id}` records from current operator authority. The migration
rejects buyer assignments and validates all historic attempts; missing backfill
fails the migration. No activation with orphan attempts or unvalidated constraints
is permitted. New-order assignment provisioning, authorized historic backfill and
database rollout proof remain deferred to runtime composition. Assignment absence
on an active callback is therefore a broken database invariant, never a supported
financial state or a reason to run expiry against an unassigned deployment.

Release gross excludes buyer fees already recognized by confirmed refunds. Its
buyer-fee deduction includes only the unrecognized remainder. After a full watch
refund and separate seller collection, remaining accepted transport/tax can settle
through the same authorized release primitive with zero `transfer_minor`: debit
remaining held funds and credit the retained transport/tax liabilities, with no
seller transfer or repeated fee recognition. The serialized policy reader must
explicitly grant `charges_ready` for these accepted liabilities, with no current
hold. This branch requires full confirmed principal refund and no remaining fee
deduction; it does not require or invent buyer receipt, an inspection pass or a
payout window. Ordinary transfers retain all current release prerequisites. Signed breakdowns, original operation retries and once-only postings remain
required for these settlements.
