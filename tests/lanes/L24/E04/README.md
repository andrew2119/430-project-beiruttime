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

## Connected PostgreSQL restore

From the repository root, run:

```
/opt/bt/bin/python tests/lanes/L24/E04/connected.py --run-dir "$RUN"
```

This command requires a running native stack, PostgreSQL 17 client/server
executables on PATH, an unprivileged operating-system user able to run initdb,
and an unused local port (55439 by default; override with `--restore-port`).
It neither starts domain services nor calls payment, email or SMS providers.
The source is restricted to 127.0.0.1:54329. RUN must be outside the checkout.
It consumes RUN/native-v1.json with schema_version 1 and
services.<domain>.env.BT_MIGRATION_DATABASE_URL (or BT_DATABASE_OWNER_URL).
Runtime credentials are never used as an owner fallback. All nine databases
must be distinct. Configuration files must be regular private 0600 files.
Passwords are passed through a restricted child environment, never command
arguments, output or summary records.

The connected input prerequisite is RUN/e04-inputs.json, also 0600. Its shape is:

```
{
  "schema_version": 1,
  "origin": "connected",
  "probes": {
    "I07": {"domain": "identity", "operation_ids": ["<actual operation id>"], "query_id": "<reviewed producer read version>"},
    "O08": {"domain": "orders", "operation_ids": ["<actual operation id>"], "query_id": "<reviewed producer read version>"},
    "S11": {"domain": "service-operations", "operation_ids": ["<actual operation id>"], "query_id": "<reviewed producer read version>"},
    "A10": {"domain": "trust", "operation_ids": ["<actual operation id>"], "query_id": "<reviewed producer read version>"}
  },
  "file_store": {
    "domain": "identity",
    "operation_ids": ["<actual operation id>"], "query_id": "<reviewed current file read version>"
  }
}
```

Run input selects a query_id from the code-owned PRODUCER_READS registry;
SQL in run input is rejected. The registry is currently empty because reviewed
producer reads establishing durable operation provenance are unavailable.
The command therefore fails closed with verified_producer_read_unavailable:I07;
no supplied query or origin label can turn that absence into connected proof.
Registering a read requires review of its version, fixed domain, durable
operation lookup, exclusion of seeded records and derivation of all assertions
from current producer facts. This applies to file metadata reads as well.

Producer queries run read-only with operation_ids bound as `$1` (a text array).
Each probe must return exactly one row per requested actual operation, with
operation_id, passed=true, and these Boolean columns all true:

- I07: deletion_preserved, revocation_preserved, retention_preserved.
- O08: principal_preserved, fees_excluded, journal_balanced.
- S11: actual_receipt_preserved, current_checks_preserved, custody_preserved.
- A10: dispute_hold_preserved, release_authority_preserved, totals_preserved.

Queries must derive these assertions from the producer's actual records and
current scoped authority, including retained quote amounts, principal-only
refunds, journal totals and current custody/dispute/release facts. Constant
SELECT results, seeded operations and substitutes are not connected proof.
The adapter does not create producer records. The fixed consumer read contract
is described below; its production views and real operation ids remain required.
The file query must return exactly one row per requested operation with
operation_id, current=true, file_id, tombstoned, checksum (SHA-256), size and
content (the actual database bytes for retained files). The content and metadata
must share the source transaction. The byte representation accepts at most ten
files of at most 262144 bytes each. It writes only private directories and 0600
files, never a second serving store. It does not require a production filesystem
root. Manifest entries contain metadata, never content.

After export, a fresh source transaction reads current authority. Missing,
duplicate, denied or mismatched operation references fail closed. A current
tombstone suppresses older bytes; changed checksum or size is stale and fails.
All permitted bytes are verified before creating the private restore destination.
This is a representation boundary, not proof that current producer authority
exists. Production implementations remain unavailable in this copy: durable deletion
metadata, current grants and retention decisions must be supplied by the owning
producers before connected acceptance. No byte row or operation supplied by a
caller establishes that provenance.

Each database dump uses an exported repeatable-read snapshot, held open until
pg_dump completes. Canonical complete-row hashes and counts cover every user
table, including migration, journal, custody and durable operation records.
Producer assertions must pass on the source snapshot and the restored
database. Identity is refreshed from current source authority before restored
content hashes or assertions are read; its assertions are compared with a fresh
source read rather than the older backup. Snapshots are per database, not a distributed
transaction: run with domain writes and file mutations quiesced for a coherent
cross-domain backup. This command does not claim to coordinate live writers.

The command initializes a fresh private PostgreSQL 17 cluster, restores all
nine dumps, creates the private NOLOGIN runtime role e04 required by the
shared runner for owner e04_owner, then tests transactional migration failure/rollback, retry,
duplicate, checksum rejection and unknown-ledger rejection against each private
database using the shared migration runner. It verifies that all original rows
remain identical afterward. Source databases receive read-only queries only.
The temporary cluster is stopped and its dumps and files removed on exit.

Identity reconciliation uses fixed relations: private evidence, possession
photos, listing reviews, private assignments, access grants, refresh tokens,
reauthentication proofs, password resets, sessions and accounts. Current account
status, password and access revision replace the backed-up authority; session
revocations and credential consumption are refreshed before restored reads.
Missing dependent credentials are removed before their sessions.
It reads current rows in one repeatable-read transaction before inspecting old
identifiers, removes missing rows and refreshes existing rows atomically in the
private destination. New source grants are never inserted into the backup.
Each relation is bounded to 1000 rows; unavailable relations, excessive rows or
invalid identities abort restoration. Every unrelated table must retain its
original digest. Reconciliation counts contain no private values. This closes
the ordering gap for these relations; it does not establish missing durable
operation provenance or producer retention decisions.

RUN/scenarios/e04/summary.json is private and contains the source revision,
scenario ids, passed/failed states, original operation ids, measured seconds for
the complete connected exercise, database row counts and digests, and named
missing capabilities. Valid operation references, including file-store references,
are retained even when a producer read is unavailable; database restore and
migration cases list the combined references covered by the exercise. Invalid
reference lists are omitted without discarding other valid lists. Retaining
references does not establish connected acceptance. It contains no row values
or credentials. All required
cases must pass to return zero; incomplete runs return nonzero and never count
local tests as connected. Connected execution remains deferred until run on the
native stack with producer inputs. Successful synthetic checks alone establish
no connected acceptance.

Focused checks (no service connections):

```
/opt/bt/bin/python -m pytest -q -p no:cacheprovider tests/lanes/L24/E04
```

The recovery sequencer requires an owning runtime composition. It orders a real
backup before deletion, revocation and retention commands, compares current
watermarks and expected redactions, checks unaffected digests and rejects unsafe
restores. It also orders lost-response dispatch, interruption, restart, lookup
and two concurrent retries of the original operation for acknowledged and held
unknown outcomes. Select the installed owning composition with
`--recovery-runtime MODULE:FACTORY` on the default, `--retain-backup` or
`--consume-backup` invocation. The factory is called with keyword arguments
`run` (the private run directory) and `operations` (the original validated
operation references). It returns an asynchronous context manager yielding the
runtime described below. All thirteen runtime methods must be asynchronous.
The context remains open through recovery and publication, and closes on success
or failure so the owner can reclaim clients and processes. The option selects
executable code from the installed environment; run input cannot select code or
supply a preparation summary. Without the option, recovery still fails closed
with `owning_recovery_runtime_unavailable`. Local doubles prove
sequencing only. Temporary artifacts are removed by default.


A private retained handoff is available with `connected.py --run-dir RUN
--retain-backup BACKUP`. The target must not exist and must be outside the
checkout. Only nine dumps, bounded byte files and a versioned manifest survive;
cluster passwords and logs are never retained. The manifest binds dump hashes,
migration-ledger digests, source revision, inventories and the original operation
references. Manifest version 2 requires operation-bound deletion, revocation and retention
watermarks from the reviewed I07 source read. Each watermark is a positive
durable revision, not a reconciliation count or a caller-supplied flag. Missing
watermarks prevent publication before any output directory is created. On
consumption, fresh source revisions must cover every saved revision; rollback
is rejected. Version 1 manifests cannot authorize a restore.

Run `connected.py --run-dir RUN --consume-backup BACKUP` to restore those actual
dumps into a newly initialized isolated PostgreSQL 17 cluster. This invocation
verifies all nine hashes, the revision and operation bindings before starting,
compares restored rows and producer probes, reapplies fresh source Identity
authority and checks byte integrity. The retained backup is reclaimed after the
attempt, including when restoration fails; invalid inputs are left untouched
for explicit private disposal. Default invocations still remove everything.
The release consumer must invoke this restore, never accept the manifest alone.
Connected acceptance still requires the missing producer registry, durable
privacy watermarks and the recovery sequences described above.

The I07 read must additionally return deletion_watermark, revocation_watermark
and retention_watermark for each operation. These fields must identify durable
producer authority revisions. This boundary validates their shape and monotonicity;
it cannot create absent producer records or replace a reviewed source read.
Production source views and the owning recovery runtime remain prerequisites;
no local unit result establishes connected acceptance.


## Fixed producer read contract

`producer_reads.py` registers exactly five consumer reads. Query identifiers are
`e04.i07.v1`, `e04.o08.v1`, `e04.s11.v1`, `e04.a10.v1` and
`e04.file_store.v1`. Their fixed domains are identity, orders,
service-operations, trust and identity, respectively. Each selects its named
fields from `public.e04_<name>_v1`, with the name in lowercase, restricted by
`operation_id = ANY($1::text[])`. No caller SQL or relation name is accepted.
There are at most ten requested operations; an eleventh returned row detects
excess or duplicate results. These are consumer contracts, not installed views
or reviewed production implementations. An absent view fails restoration.

Every row must contain `operation_id`, `producer` (the exact registry key),
positive integer `source_revision` and `authority_revision` that match,
`durable=true`, `seeded=false`, `synthetic=false` and `authorized=true`.
Producers must derive these values from durable authenticated operation receipts
and current serialized authority, never caller assertions or constant flags.
Receipt provenance and current authority must share the read transaction.
Missing, duplicate, denied, stale or cross-operation results fail closed.
Probe rows additionally contain `passed` and the invariant fields listed in
`connected.py`; every invariant must be a measured Boolean. I07 additionally
provides the three durable privacy watermarks. File rows contain current byte
metadata and content as described above. This folder installs no source views,
writes no source rows and creates no second production store.

`recovery_cases.py` defines the runtime composition boundary. `measure` returns
source-measured privacy watermarks, exact opaque redaction identities,
unaffected table digests and stable effect maps for charges, payouts and
custody. `backup`, `restore`, `restore_rejected` and `discard` own isolated
private backup handles. Rejected restore attempts operate on private copies.
`command` invokes authenticated producer deletion, revocation and retention;
it cannot update rows directly or override retention clocks. Replay methods
must bind the original immutable command, deliberately lose its response,
interrupt and restart the owned domain process, and read effects at their
owning sources. Unknown outcomes remain held. `effects` returns fresh maps
from durable result identities to immutable totals or custody receipts.
Acknowledged replay may add at most one result of each kind on dispatch and
none on duplicate retries. Each of O08, S11 and A10 requires separate actual
acknowledged and held-unknown operation references.

This copy lacks the durable I07 deletion metadata, PostgreSQL views for these
producer facts, and native process ownership needed to implement that boundary.
The source modules expose local stores or injected provider interfaces instead.
No implementation is fabricated here. Connecting those owning implementations
and executing the real PostgreSQL 17 rehearsal remain deferred. E09 is outside
this folder's lease and still needs to consume a measured restore invocation.

Before any Identity reconciliation, the restored inventory must equal the saved
inventory, including every byte-bearing table. Retained bytes must also match
current source size and checksum; they cannot be repaired from source content.
An explicit current null photo or absent row permits redaction. After each
relation is reconciled, its complete rows must equal the measured projection of
current authority onto the backed-up identities; unrelated digests stay fixed.

Replay effect maps are scoped to the original operation. A first result value
must contain that exact `operation_id` alongside its immutable receipt or total.
Once a kind has a result, dispatch and retries must preserve its complete map.
Measurements are snapshotted so later mutations cannot rewrite earlier results.
