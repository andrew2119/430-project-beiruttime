# Assigned identity review v1

Only purpose-specific synthetic identity facts enter this boundary. Identity review does not consume payment readiness, capacity, wealth, deposits or instalments. Approval never grants execution, charging, receiving or release authority.

`models.py` defines strict command, current source and evidence schemas. IDs are UUIDs; revisions are positive integers (the initial case revision is zero). Unknown fields are rejected. The source is an authenticated, current provider response, never command input or a projection. Its aggregate source revision must advance on identity, business, consent, request, watch commitment, retained quote, objective policy or same-case staffing changes. Retained economics do not expire execution restrictions. No evidence is published in events or operation receipts.

| Operation | Versioned route | Rule |
| --- | --- | --- |
| claim | POST /v1/private-reviews/{case_id}/commands | Current assigned independent reviewer only |
| reassign | same command route | Current assignment operator; target must be independently qualified |
| correct | same command route | Assigned reviewer; reason required; preserves decisions |
| decide | same command route | Assigned reviewer; current consent, scope and accepted quote |
| current | GET /v1/private-reviews/{case_id} | Recheck current private access; returns current verdict only |
| history | GET /v1/private-reviews/{case_id}/history?page=1 | Recheck access; server total and 25-row pages |
| evidence | GET /v1/private-reviews/{case_id}/evidence | Assigned reviewer only; audited; no-store |
| operation | GET /v1/private-reviews/{case_id}/operations/{operation_id} | Current access; actor-bound stable receipt |

A command carries the exact binding, case revision and assignment revision. Initial assignment uses reassign at revision zero. Claim never selects an arbitrary unassigned case. Operator permissions do not grant evidence access. Buyer, same-case brand approver, inactive staff and removed assignees cannot read or decide. A changed source invalidates the current verdict without rewriting history. Reassignment resets review state and increments assignment revision.

Receipts bind the entire canonical command and authenticated actor. Identical retry returns the same receipt; changed fields conflict. Access is checked before replay. An uncertain or lost response remains pending: look up or retry the exact operation ID. Denied is 403, stale/conflict 409, invalid 422, missing 404, unavailable/timeout 503. All responses are private/no-store. Missing source facts never imply approval.

The repository transaction owns case state, immutable decision history, command receipts, audit and outbox together. Source validation must share a serialized invalidation fence with current provider authority before connected acceptance. The included source port is a contract freeze, not an existing remote endpoint. No local stub is production authority.

D31: no uploaded bytes are accepted here. Unsubmitted evidence is cleared after seven days; reviewed synthetic facts after 30 days unless an active obligation requires them. Minimal references remain one year. Deletion requests complete within 30 days after obligations close; export is due within seven days. Export uses the same current private authorization. Retention removes decision reasons with evidence; reference-only receipts remain for retry, never restore erased content.
