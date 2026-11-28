# Private inspection v1

`v1.py` defines strict immutable command and current-source schemas. Integer amounts are USD cents. Provider instants must include an offset and are normalized to UTC. A current source is usable at checked_at and strictly before valid_until. Civil appointments, when supplied by custody, use Asia/Beirut; this module never invents an appointment or receipt.

Proposed operations, supplied through the owning service's authenticated boundary:

| Operation | Purpose |
| --- | --- |
| GET /v1/private-inspections/{subject_id}/workspace | Current private command bindings and authorized reference count; no evidence previews |
| POST /v1/private-inspections/results | Submit `Submit`, maximum 16 KiB |
| GET /v1/private-inspections/operations/{operation_id}?subject_id=… | Recover the same actor/organization's durable acknowledgement |
| GET /v1/private-inspections/{subject_id}/current | Recheck current authority and all source bindings before returning current result facts |

The host supplies authenticated actor and selected organization, never from untrusted body fields. Every read and write checks current identity, record scope, assignment and source. A dependency deadline is 1.2 seconds. Missing, malformed, expired or uncertain facts are unavailable. Authorization failure is denied. A changed source or result revision is stale; refresh and explicitly review before a new operation. Conflicting operation reuse is denied. Lost response retries retain the exact operation and command. An identical retry may recover its historic acknowledgement after a newer result, but that acknowledgement is never current execution permission.

The current-source provider composes current identity, independence/assignment, exclusive watch commitment, retained exact economics, Orders paid-held readiness and the early signed expert custody receipt. It must not require final buyer handover. All revisions are bound. Evidence references must already be authorized for this exact actor, organization, inspection and watch revision by the evidence provider. Byte uploads are outside this interface; it accepts at most twelve opaque references, never links, previews or file bytes. No evidence references or free-text reasons enter outbox payloads or logs.

Dealer/brand requests are rejected with an explicit business-assurance route, never a pass. A private pass is only an inspection prerequisite; buyer handover and payout still require their own current Orders/custody/window/hold decisions. Failed and inconclusive results block both. Only failure publishes seller-charge-required and buyer-watch-price-refund-ready facts. Refund readiness is an authorization basis for watch principal only, never confirmation of money or permission to refund fees. Orders remains the sole money authority.

Failure produces one stable simulated collection operation for the retained 5% commission plus accepted return trip. No payout deduction is invented. Unknown/declined collection blocks return, restricts new private publication and gives support a 24-hour follow-up. It does not block a permitted principal refund. Controlled return additionally requires a current matching confirmed collection and custody instruction bound to the same watch, watch/source/result/assignment revisions and expert receipt. A failure cannot be replaced by a pass through this ordinary operation; further resolution requires a separate reasoned operational decision. Inconclusive may receive a new attributable decision at the current revision.

Outbox payloads are minimal private internal facts with stable event IDs. Dispatch and inbox integration belong to the host. Consumers deduplicate event IDs, fetch current facts, and never execute from the event/cache alone. The local durable adapter atomically saves the result, operation acknowledgement and outbox rows; it is not a financial journal. Production persistence and HTTP composition remain with their service owner.
