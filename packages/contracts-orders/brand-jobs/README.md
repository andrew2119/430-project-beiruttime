# Brand jobs v1

The private command and operation lookup are defined in `contract.py`. Requests contain references only, never evidence or payment credentials. Current provider reads must be authenticated, scope checked and bounded to two seconds. Missing facts remain unavailable. A projection cannot authorize execution.

Authorization consumes a serialized current scope through the canonical Orders commitment owner. Its `authorize_once(command, scope)` must recheck all source revisions, consume the execution grant for customization, retain the existing exclusive watch allocation, and atomically persist one job, its operation receipt and outbox event. It must never create a second allocation or journal. A repeated operation returns the original result; changed content conflicts. A timeout requires lookup with the same reference. The local receipt store is durable retry coordination, not financial or custody authority.

Repair uses the separate paid-scope operation with an accepted S02 service scope and O03 held payment. It does not require customization approval, eligibility or customization consent. Ordinary repair still requires current service permission, qualified assignment and exclusive allocation. Material scope change requires new explicit acceptance.

Responses use schema_version, operation_id, subject_id, watch_id, actor_id, organization_id, expected_revision, state, revision, pending_reason, next_actor and next_review_at. States are authorized, denied, stale, pending and unavailable. Pending references remain stable after restart. Reads recheck current identity and business scope before returning a receipt. No response grants authority to release funds. Release belongs to Orders and requires actual current quality pass, actual receipt, the 168-hour elapsed window and no dispute or incident hold.

Runtime registration, actual producer integration, database transaction/outbox proof and connected restart journeys remain required before acceptance.

Canonical `lookup_operation(command)` returns the immutable original job and assignee with the exact command binding and source revision, or no recorded effect. Lookup never starts work. The local immutable outcome is separate from the current permission response; assignment changes remain held until authoritative reconciliation, never relabel the original job.

`assign_recovery(command)` durably assigns a specific operator, next action, escalation recipient and authoritative UTC opening instant once per binding. Held receipts retain this assignment, the 24-hour first-response deadline and 48-hour escalation deadline across reads, retries and restart. The recovery owner performs response and escalation; missing assignment availability is unavailable, never an invented operator. These producer integrations and scheduled execution remain connected proof owed.

Repair commands freeze the acceptance reference and accepted total through `repair_binding(command, acceptance)` before any pending response. Use that exact binding for authorization and lookup. Payment operation, payment revision and order are current source facts rechecked by the canonical operation, rather than values appended when payment becomes held. Optional caller-supplied payment bindings remain immutable and must match current facts.
