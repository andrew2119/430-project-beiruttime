# Repair quotes v2

`models.py` exports the bounded USD issue, accept and decline schemas. Issue requires a current diagnosed service case, current business authority and the exact assessed mandatory/optional lines. Acceptance binds quote revision, terms digest, every mandatory line, selected optional lines and the exact total. Assessment and return transport have separate explicit consent flags. Return transport is disclosed separately and is never silently added to the job base. The business pays one 5% fee, rounded half up; the customer pays no surcharge.

Operations:

- `GET /v1/repair-quotes/context` resolves current assessed scope.
- `POST /v1/repair-quotes` issues a preview lasting at most fifteen minutes.
- `GET /v1/repair-quotes?page=1` returns twenty scoped records, page size and server total.
- `POST /v1/repair-quotes/{id}/accept` records buyer consent only.
- `POST /v1/repair-quotes/{id}/decline` records controlled unrepaired return, including after preview expiry. No current diagnosis is required to refuse work.
- `GET /v1/pricing-operations/{key}` retrieves the retained result in the current actor/business scope. A missing result is not proof of failure; retry the original command with the same key.
- `GET /internal/v3/quotes/{id}/validation?buyer_id=...` is the authenticated current-economics boundary. Retained economics with no expiry never confer execution permission.

A bounded `Idempotency-Key` identifies each command. Identical retries return the transactionally persisted result; changed fields with the same key conflict. Decision, outbox and receipt share the existing Pricing transaction. Reads and retries require current identity and record scope. Provider uncertainty returns unavailable without a guessed acceptance. Errors use stable codes: `source_changed`, `scope_mismatch`, `quote_binding_mismatch`, `quote_expired`, `quote_not_current`, `fee_consent_required`, `idempotency_conflict` and `dependency_unavailable`.

`policy.py` rejects changed diagnosis, parts or mandatory flags even if a producer mistakenly retains its revision. Before/equal/after expiry is strict for acceptance; silence and expiry never create a decision. A declined quote preserves custody and only its explicitly acknowledged fee lines. A fee acknowledgement is neither incurred work nor confirmed collection.

Accepted scope is immutable history. New fault, part or amount requires a replacement quote and renewed consent. Execution belongs to the service lifecycle and requires current authority, canonical watch commitment, custody, accepted scope and Orders-confirmed platform-held simulated payment. This module creates no execution, custody transfer, collection, balances or release authority.

The deterministic fixture covers success, denied, stale, expiry, unpaid execution and lost response. Provider-connected commitment, custody, payment, timeout/restart and cross-service serialization remain separate integration requirements; local fixtures do not satisfy them.

Acceptance currently fails closed with `dependency_unavailable`: the current diagnosis read does not supply a source-owned serialized authorization fence. A replacement boundary must bind current actor/business authority, assignment, subject/watch and diagnosis revisions to the stable operation and hold them through the Pricing transaction commit. A preflight read or local quote lock alone cannot satisfy this requirement. Decline and retained-result recovery remain available.

Controlled return recovery uses `recovery.py` version 1. The assignment producer must reserve one currently authorized operator for the quote, buyer, business and original operation until the decision transaction commits. The local boundary is unavailable until that producer is connected; decline then remains unconfirmed and must retry its original reference. Missing, mismatched or uncertain assignment never creates an ownerless held decision.

The decline transaction stores `repair_recovery` with the assignment identifier/revision, responsible operator, fixed next action, held timestamp, first-response deadline at 24 hours and escalation deadline at 48 hours without progress. The retained receipt, scoped list and transactional event include this recovery record. Retries return the original record without restarting deadlines. At equality the corresponding response or escalation is due. The additive migration does not invent responsibility for historical records. Connected assignment reservation, historical backfill and scheduled follow-up/escalation delivery remain deferred; stored deadlines alone are not proof of delivered follow-up.

An expired preview without a durable recovery assignment remains `issued` in the repair read model with `return_coordination: "unavailable"`. Its deadline still denies acceptance. The interface displays expiry and unavailable coordination, never an established held outcome; custody release remains forbidden. Assignment and scheduled expiry coordination remain deferred.
