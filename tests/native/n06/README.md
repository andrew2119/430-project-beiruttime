# Native lifecycle contract v1

`python3 scripts/native-lifecycle.py --proof all --plan` prints the offline plan.
`--proof` also accepts dependency-outage, process-restart, database-restart and
replay. `--run-dir DIR` reserves the execution interface. Execution currently
returns 2 with deferred prerequisites; it never treats missing providers as a pass.
No connected invocation is authorized by source completion.

The importable `exercise(provider, proof, run_dir)` is the owned process evidence
adapter. Its local tests inject all process, database and request effects.
N01, N02 and N04 connected bindings are deferred. Provider-specific operation and
event behavior requires A10, E04 and E06; no endpoint is invented here.

Provider methods are synchronous and accept an enforced timeout in seconds:
start (30), observe (5), operation (10), disrupt (10), isolation (10), restore
(30), database_restart_evidence (5), recovered (30), retry (10),
replay_evidence (5), cleanup (30).
Their positional arguments are specified by the calls in the driver. No method
may exceed its timeout or poll indefinitely. They must use current reviewed
versioned provider interfaces and only the named replica's endpoint namespace.

start returns the versioned ownership record: schema_version
`bt.native.lifecycle.v1`, run_id, canonical run_dir, pid, process start_time,
owned_replica=true, domain, runtime_kind (`owning` or `foundation-fallback`),
explicit numeric loopback HTTP origin url, and database {id, run_id,
disposable=true, restricted=true}. A fallback additionally supplies its exact
image. N01 must verify these facts, not accept user declarations as ownership.
observe returns the current record using process start-time identity, never a
command substring. Every destructive provider method must atomically recheck
identity before acting, including restoration and cleanup. Shared services are
never eligible. No database credentials belong in this record.

start durably registers every replica before returning or exposing it, including
replacement processes. Partial start failures clean themselves up. cleanup
attempts every registered replica, refuses foreign identities, and reports all
failures nonzero. restore is idempotent and works after partial disruption;
interruption must unwind through restoration and cleanup. A separately authorized
execution binding must route termination through this unwind as well.

operation and retry return operation_id, subject_id, durable_reference,
state_digest, effect_count, outbox_reference, inbox_reference, outbox_pending,
inbox_effect_count. References come from retained authoritative operation and
event records. retry must submit the same operation reference, drain replay and
read back its actual durable effect. Digests cover retained business data, not
health or volatile timestamps. Exactly one effect and inbox application must
remain after replay; pending outbox work must converge within the bound.
For replay, replay_evidence(record, operation_id, timeout=5) is read before
interruption and after retry. Both observations bind operation_id,
outbox_reference, inbox_reference, run_id and database_id to the same retained
operation and owned storage. They contain nonnegative integer cumulative
outbox_delivery_count, inbox_delivery_count and inbox_duplicate_count from
retained delivery records. Initial outbox and inbox delivery counts must be at
least one. All three counts must increase after retry: the same event is delivered
again and the inbox suppresses its duplicate while the effect remains exactly one.
An unchanged already-converged operation fails. Counters must be scoped to these
exact references, never aggregate traffic or invented declarations. This is a
proposed binding contract pending the versioned provider inputs.
No fixture can establish connected business success.

disrupt targets only the selected replica or its owned disposable database.
Database restart evidence names database_id plus distinct nonempty before and
after process start times. Process restart and replay require actual owning
runtime PID and start-time changes with the same database and retained operation.
Object reconstruction cannot satisfy this contract.

isolation returns shell_available, catalog_available, unavailable_domains,
domain_statuses, dependency_status, error_code and request_id_present.
domain_statuses maps exactly identity, eligibility, catalog, auction, pricing,
communications, orders, trust and service-operations to their observed status
from the complete status response. The disrupted domain must be unavailable and
every other domain ready; missing or extra entries are refused. Only the disrupted domain
may be unavailable, with status 503 and unavailable error. The adapter requires
the exact fallback image declared above. recovered checks the restored dependency
and unaffected shell and Catalog within 30 seconds.

Acceptance also requires comparison of every native mapping with the original
lane assertions and fallback ownership guard. Local stubs establish only this
adapter's declared contract; they cannot establish preservation of those originals.
The offline plan exposes `acceptance_checks.original_mapping_comparison` as
`deferred` until original context can be compared independently.

The explicit lease covers this script and this test subtree and is authoritative
for this change. The offline plan retains recursive_lease_overlap as deferred
because the wider register is unavailable; it is not a prerequisite for preparing
or reviewing this owned source change.

Deferred proofs: real database interruption/restoration, native process ownership
and restart, connected operation/outbox/inbox replay, browser isolation, load and
physical-device checks. Existing lane drivers stay read-only. No native heavy
execution, provider behavior, independent acceptance or release is asserted.
