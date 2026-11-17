# Synthetic migration and restore preparation

Run `python tests/lanes/L24/E04/run.py` with the repository Python environment.
The command prints a versioned result manifest to standard output. It writes no
result records into the repository. Test stores live only in temporary folders.

`contract.json` defines operation lookup, binding requirements, states, limits,
retention and remaining proof. `fixtures.py` supplies deterministic synthetic
role, seller and business combinations. No seeded state establishes an accepted
bid, payment, inspection, receipt, completed job or payout.

The migration checks read all nine committed module registrations and compare
checksums against their SQL bytes. They exercise the shared migration runner's
failure rollback, retry, duplicate, changed checksum and unknown-ledger handling
through a transactional substitute. They do not execute domain SQL.

The restore model copies nine isolated synthetic stores and private file metadata
to a fresh private destination. It checks file bounds and integrity, applies
current deletion tombstones before copying files, refuses absent current facts,
and reports missing files explicitly. A destination is never a serving root.
Reads recheck current scoped bindings, revocation and retention at each access.
An old active-case flag cannot override current retention. Case preservation
is limited to reviewed identity/possession proof and requires current case and
assignment assertions bound to the file, every read binding, the same case and matching positive revisions. Both must be active and
the case must explicitly need the evidence. Missing, revoked or cross-scope
assertions deny access; revision mismatches return stale. No caller override
can extend retention. Unsubmitted uploads remain inaccessible at and after seven
days, including with valid case assertions; audit references expire at one year.
All fixtures are private test inputs; there are no public previews or customer-facing screens in this change.

Replay only looks up the original bound operation, with at most two timeout
attempts. Unknown results remain pending. A stored receipt cannot authorize a
new effect. The local receipt replacement demonstrates reopening a result,
not crash-safe production durability. Reconciliation returns findings and
holds only; it cannot call a journal, release funds or manufacture custody.

Connected finishing remains owed for I07, O08, S11 and A10: actual provider
schemas and operation lookup, all nine database restore/migration execution,
file and metadata backup consistency, current tombstone/revocation watermarks,
durable inbox/outbox receipts, process interruption, concurrent retries,
retained quote and journal totals, and current custody/dispute/release facts.
Replace each substitute with its producer's exact version and repeat success,
denied, stale, timeout, duplicate and lost-response cases. An old backup must
not restore a deleted file, revoked grant, charge or payout.

Database execution, connected stacks, release execution and browser/device
checks require separate-machine clearance. These local checks do not establish
integration or release acceptance. No interface or page has been added, so
frontend lint, type checks and visual checks are outside this diff's scope.
Full external schema validation remains deferred; the local check verifies the
declared fixture fields, scalar constraints and UTC follow-up values directly.
