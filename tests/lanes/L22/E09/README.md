# Release recovery preparation

This module publishes a versioned operation binding, operation lookup, synthetic
fixtures and an executable required-check manifest. It does not execute release
commands or certify a provider. The fixtures never authorize money, custody,
approval or release. No accepted transaction is seeded as connected proof.

Run the local module checks from the repository root:

```
python -m unittest discover -s tests/lanes/L22/E09 -p 'test_*.py'
python tests/lanes/L22/E09/recovery.py
python tests/lanes/L22/E09/recovery.py /tmp/release-record.json
```

The first manifest contains deferred entries only. Keep execution records and
private artifacts outside the repository. The record checker returns nonzero for
missing, skipped, deferred, conflicting or unsupported results. Its acceptance
means submitted declarations meet the record contract; a person must inspect the
referenced artifacts. It cannot establish the truth of submitted declarations.
Do not include private evidence, private ceilings, recipient addresses, passwords
or file bytes in a record, public preview or diagnostic output.

## Required connected finishing

E04, A10, E08, O11, S12, M08, M09 and E06 remain prerequisites. Current producer
versions must replace the fixtures. Repeat stale, denied, cross-account, timeout,
lost-response, duplicate and restart cases after replacement. Reads and writes
must recheck identity, business, assignment, scope and revision. A cache is never
permission. Pending results retain the operation reference and responsible person.

The operation lookup contains published freezes, not endpoint-discovery claims.
Quote validation includes the buyer query parameter and authenticated internal
consumer. Retained reads and commits are Orders-only. Commit binds buyer, order,
quote revision, total cents and serialized UTC commitment time. Retained economics
never imply execution permission. Durable buyer notice and verified synthetic
recipient availability precede the payment clock. Duplicate notices must match
the original event, buyer, order and availability instant exactly.

Competition runs only under canonical serialized admission. Only the leader has
an active private ceiling. Select the band at the challenger amount, require a
full-step response and never publish an equal bid or private maximum. A displaced
ceiling stays inactive until raised. End time never extends.

## Separate-machine execution plan

Explicit separate-release clearance is required before production builds, complete
suites, connected services, load checks or the visual matrix. No such command is
launched by this module. Each of the nine domains has independent build, suite,
dependency and vulnerability entries. Record the exact command, exit status,
immutable synthetic build, artifact reference and independent repeat against that
same build. Copied screenshots and outside benchmarks do not establish a pass.
Any reproducible S0/S1 defect blocks acceptance, including an otherwise green run.
A skipped check needs its reason and remains owed. A provider unavailable during
execution remains deferred, never replaced by fixture success.

Every named journey has positive, denied, stale, cross-account, timeout,
lost-response, duplicate, restart and before/equal/after cases in both languages.
Reconcile this matrix with all 64 feature journeys before release; this named
subset alone is not full coverage. Purchase, customization and servicing each
require connected permission, money, custody, recovery and negative proofs.

Visual proof covers both languages and themes, desktop and 390 by 844. Measure
`window.innerWidth === 390` and actual height; include overflow, 44px targets,
16px coarse-pointer inputs, focus/keyboard, reduced motion, RTL, safe areas,
loading/empty/denied/pending/error/retry/unavailable states. Preserve mounted form
identity, all inputs, private files in memory and operation references during
language changes; verify private views clear on access change. Test mixed long
text, emoji, missing data, counts 0/1/large and 1000 rows with server pagination.
Physical-phone proof remains separate from viewport checks.

Speed proof names each actual page read key, intent warming, retained answer,
refresh content, first-load placeholder, single arrival fade and first-frame
contract, with measured per-page size gates. Missing source improvements remain
source-version gaps. Load proof records a bounded dataset, connection, durations,
nearest-rank p95, errors and a predeclared threshold; no target is inferred.

## Manual version, rollback and restore rehearsal

1. Record current source revision, schema versions, nine domain artifact versions,
   configuration revision and synthetic dataset identifier. Keep a compatible
   previous version and a verified backup with a restore point. Record the owner,
   expected recovery time and permitted data-loss bound before execution.
2. On a cleared isolated environment, acknowledge an operation, lose its response,
   restart and retry that same reference. Verify durable state, inbox/outbox
   receipts, original economics and no duplicate commitment or journal entry.
3. Reconcile orders, notice availability, payment attempts, holds, refunds, fees,
   custody and immutable recipients against authoritative receipts. Unknown money
   stays held. No attempt or only final declines may release stock atomically.
   Equality is expired; an eligible earlier attempt gets only one extra window.
4. Restore the backup into an isolated destination. Replay only stable receipt
   references; compare acknowledged operations, revisions and reconciliation
   totals. Record actual recovery time and missing acknowledged changes. Any lost
   acknowledged change blocks recovery acceptance.
5. Rehearse rollback to the compatible prior version without undoing applied
   migrations or rewriting history. If compatibility is absent, stop admission
   and use a forward correction; never guess or silently discard writes. Verify
   current permissions and pending holds again before reopening admission.
6. Keep the actual restore/rollback transcript, limitations and responsible next
   action outside the repository. A written guide alone is not execution proof.

## Five-owner explanation rehearsal

Record five distinct named owners and an independent repeat. Each explains the
invariant, source authority, current version, observable denial and recovery:

- Identity/scope: immediate revocation, assignment independence and private access.
- Competition/commitment: one watch, fixed end, one winner and stable retry.
- Economics/money: retained USD cents, one journal, nonrefundable collected fees,
  refund principal, unknown holds and job fee receivable without duplicate refund.
- Custody/quality: actual receipt, separate reviewers, current tests and incident holds.
- Experience/recovery: bilingual retained inputs, actual phone geometry, honest
  unavailable states, version rollback and restored acknowledged changes.

All connected execution, nine-domain heavy checks, dependency/vulnerability
assessment, receipt reconciliation, full 64-feature mapping, owner rehearsal,
load, visual checks and physical-phone proof remain owed until recorded against
the current build. No deployment or workflow change is part of this module.

## Connected recovery driver

From the repository root on beirut-test-1, with the native stack already running:

```
E09_MODE=rehearsal python tests/lanes/L22/E09/driver.py --run-dir "$RUN"
```

The default mode is rehearsal. The driver writes a private
`RUN/scenarios/e09/summary.json`, including scenario identifiers, operation
identifiers, source revision, measured seconds, outcomes and the five owner
responsibilities. Exit zero requires every connected case. Run output belongs
outside the source checkout. The driver does not install dependencies.

The driver consumes the private `RUN/native-v1.json` directly. No external
release executable or capabilities file is used. Settings contain `python`, `postgres_bin`, `environment` and
`service_environment` (per-service environment dictionaries). The driver uses
the native supervisor's runtime constructor to retain generated database settings,
service routing, origins and scoped private settings, then rebinds release paths.
Provider URLs must be loopback and database URLs must use port 54329.
Settings and child output are never printed.

Replacement validates the complete environment before taking `control.lock`.
The current native supervisor retains its original process entries in memory and
publishes no ownership transfer interface. Replacement therefore fails before
termination with `native-supervisor-ownership-transfer`; a busy control lock fails
with `native-supervisor-control-busy`. No disk ledger edit is treated as a handoff.
Connected restart and rollback remain deferred until the supervisor provides an
ownership transfer interface. The current stack is left running.

Build exports the source revision into a private release directory, packages the
contracts, compiles all nine domains and builds the production web with installed
local dependencies. It never installs dependencies or reverses migrations.
Execution requires a network namespace with only loopback routes; missing isolation
is a named failure before any build command. The local simulators remain selected
by the runtime settings. No remote provider is allowed.

Authoritative reads use `e09_reads` in the runtime settings, with `receipts`,
`journal` and `custody` bindings. Each binding contains `url` and optional private
`headers`. Only the owning orders service on port 8105 is accepted; redirects and
proxy settings are disabled. Each response must contain its named nonempty array
and explicit `synthetic: false`, `seeded: false` provenance. Receipt rows contain
`operation_id`, integer `amount_minor`, USD `currency`, `custody_reference` and
`revision`; journal rows contain matching operation and money with `effect_count: 1`;
custody rows contain matching operation, custody reference and revision. These
are current reads of existing acknowledged operations, never writes or seeded
observations. Missing mounted read bindings fail by name. Final reconciliation
requires every baseline receipt to remain identical, permitting new receipts.

E04 currently publishes a synthetic restore model rather than a connected backup
output. The restore case therefore fails with `E04-connected-backup-output`;
no synthetic restore counts as connected. Connected restore and authoritative
read integration remain deferred until those owning prerequisites are available.
The command returns nonzero for these missing capabilities while retaining the
outcomes and measured durations of the other steps. Local checks prove orchestration
and process handling only; the designated-host rehearsal is still required.

`E09_MODE=railway` with the same entry point prints only the proposed commands
and exits without reading settings, writing evidence, building or executing any
command. It never deploys.
