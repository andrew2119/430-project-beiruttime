# Assessment v1

Commands: POST /v1/brand-assessments/{subject_id}/commands. Private read:
GET /v1/brand-assessments/{subject_id}. Operation lookup:
GET /v1/brand-assessments/{subject_id}/operations/{operation_id}.

The server resolves current identity, selected official business, technical scope,
qualified membership, capability, immutable five-option request, watch and assignment.
The caller cannot supply these facts as authority. All provider calls have a bounded
timeout. Missing authority is unavailable; mismatched authority is denied.

Every command binds the fields in v1.py. A duplicate operation with different bytes
conflicts. Identical retries return the retained result after current read authority
is checked. Stale request, assignment, capability or record revisions deny new writes.
Correction blocks assessment immediately, retains the old scope and reason, and sends
one durable Catalog revision request with the same operation reference. A timeout
remains pending; lookup or retry uses the same reference. Only Catalog's matching
receipt completes correction. A correction never grants execution permission.

Results include schema_version, operation_id, subject_id, watch_id, actor_id,
organization_id, expected_revision, state, revision, pending_reason, next_actor and
next_review_at. Assessment history retains source and assignment revisions.
No evidence bytes, private references, quote economics or execution permission are
published. UTC timestamps come from the server. This module schedules no appointments
and collects no money. Local fixtures are synthetic and confer no permission.

## Provider and delivery boundary

The current resolver returns active, technical, official_brand, actor_id,
organization_id, subject_id, brand_id, watch_id, request_revision, capability_revision,
request_state, base_id, caliber_id, option_snapshots, approver_id and quality_reviewer_id. It must resolve
these from current private source records with a bounded dependency call. The source
request must be submitted and contain exactly the five named dimensions. Qualification
must cover the actual base, caliber and requested interventions, not a staff title.
The resolver must fail closed during revocation or source uncertainty.

The Catalog adapter accepts catalog.request-correction.v1 with the original operation,
request, watch, brand, assessor, assignment and source revision plus reason. It returns
revised only after preserving the prior immutable five-option scope and reason and
invalidating affected execution permission. Its receipt binds operation_id, brand_id,
watch_id, request_id, previous_revision and request_revision. Lost responses reuse the
same operation. delivery.py admits one 1.2-second attempt per invocation; the runtime
must provide authenticated Catalog transport and bounded scheduling. The local store
commits correction state, history, operation receipt and delivery intent together.

Runtime composition, current provider implementations and distributed serialization
remain integration boundaries. The local durable store is a contract implementation,
not proof of connected provider behavior. It must not be used as authority for money,
consent, approval, custody or execution.

## Page delivery

The private read key is brand-assessment.v1 plus request reference, partitioned by
the existing root access scope. The shared read is open-only and immediately stale:
no private request is warmed on public navigation intent. The existing provider keeps
answers only within that access partition and draws content during refresh. Loading
uses the shared first-load skeleton; no additional provider, shell or arrival effect
is mounted. The shell owns ready-before-press navigation and shared arrival behavior.
No per-page size measurement or newer warming improvement is asserted by this module.
The page edits one explicitly selected request; it does not present a truncated queue
or invent a server total. Pending commands remain in memory with one exact reference;
language changes neither remount the form nor send a command.

Current reads preserve historic request/capability bindings and expose separate
current_request_revision, current_capability_revision and current_scope. Scope changes
redact the historic assessment and require a fresh claim. Every fresh assessment gets
an immutable identity and revision for downstream binding. Reassignment, release and
correction clear current assessment identity without deleting history. Unassigned
reads contain only a claimable summary and the current request scope; old private
receipt reads require the current claimant.

Delivery attempts are capped at five, spaced by increasing 30-second intervals.
The final reservation durably retains the follow-up assignment before transport begins,
so a process restart cannot strand an exhausted correction without ownership.
Only a matching durable provider receipt completes correction. Operator retry
admission and runtime scheduling remain the composition owner's responsibility.

## Current composition limitation

No public route entry is shipped while shared-shell registration is absent. The
bilingual authenticated view mounts the functional form for the composition owner;
it must only mount inside the existing shared read scope. The page-contract register
accepts internal routes only and is outside this module's ownership. Registration,
the public route entry, page size measurement and connected rendering remain deferred. No second provider is
created here.

The current read includes assessment_id, assessment_revision, assessor_id, feasibility,
parts, limitations and lead_time_basis. Persisted findings render separately from
unsaved edits. A record-level denial conceals findings and clears command inputs and
the pending command from memory. Part item lengths are constrained on every command.

Composition supplies assign_followup(organization_id, subject_id, operation_id), a
bounded current assignment lookup returning a qualified responsible person's reference.
It must return the same assignment for an identical operation and fail closed during
uncertainty. Correction retains responsible_operator_id, next_action, next_review_at
at 24 hours and escalation_at at 48 hours. Missing assignment rejects correction admission as unavailable. Runtime must deliver first-response and escalation work against
these retained deadlines and record progress; those connected operations remain owed.
The local deadline record does not claim an escalation message was delivered.

Watch identity changes also conceal historic findings and require a fresh qualified
claim. Reads expose current_watch_id separately from the retained watch binding.
A retained pending correction exposes its original operation reference and recovers
through the private operation lookup, without reconstructing a command after remount.
Correction admission requires a qualified responsible person from assign_followup;
a missing or invalid assignment returns unavailable and rolls back all local changes.
The follow-up provider must verify current qualification before returning a reference.
