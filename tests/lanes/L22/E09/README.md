# Release recovery preparation

This module publishes a versioned operation binding, operation lookup, synthetic
fixtures and an executable required-check manifest. It does not execute release
commands or certify a provider. The fixtures never authorize money, custody,
approval or release. No accepted transaction is seeded as connected proof.

Run the local module checks from the repository root:

```
python -m pytest tests/lanes/L22/E09
python tests/lanes/L22/E09/recovery.py
python tests/lanes/L22/E09/recovery.py /tmp/release-record.json
```

The manifest contains deferred entries only. Keep execution records and private
artifacts outside the repository. The checker returns nonzero for missing,
skipped, deferred, conflicting or unsupported results. For certification,
supply the separate review record with `--reviewed-evidence`. A cleared reviewer
supplies it after inspecting the primary and repeat artifacts. The checker
validates the submitted record and evidence bindings. The clearance process
establishes the reviewer's identity and verifies the underlying artifacts.

The review record has `schema_version: 1`, `reviewed_by` naming the reviewer,
`record_sha256` binding the exact release record, and a `checks` object keyed
by check ID. Both digests use UTF-8 JSON with sorted keys, ASCII escaping and compact separators. Each check has
two `runs`, in primary and repeat order. Each run declares its `check_id`,
`source_revision`, `build_id`, `person`, `run_id`, `artifact_sha256`,
`measurements`, `state: "passed"`, `synthetic: false` and `seeded: false`.
The repeat requires a distinct person, run ID and artifact digest. The primary
measurements and digest must match the submitted proof's `measurements` and
`artifact_ref`. Each responsibility also requires an `explanation` object
with `person` matching the claimed owner and nonempty `text` describing the
owner's measured findings. The five owners must be distinct named people.
For the nine production-build checks, release rollback and restore, and receipt
reconciliation, each run's `measurements` is its private launcher summary.
`artifact_sha256` is the canonical JSON digest of that summary. Both summaries and both
runs must use the release record's `build_id`, the SHA-256 of the same sealed candidate archive. The reviewer
verifies that both invocations exercised those exact archive bytes. Each run
has its own summary digest and run ID. The checker binds each summary
to its run ID, revision, successful build and candidate process transitions.
Both recovery checks require a continuous Orders process transition through the
candidate, callback retry and prior release, with distinct verified release artifact IDs.
They require the acknowledged callback and custody references to survive
rollback, restore and final reconciliation, plus the retained backup digest
and measured nine-domain PostgreSQL 17 restore results.

For all other checks, each run's `artifact_sha256` is the canonical digest of
its measurements. Each measurement includes `evidence_sha256`, the digest of
its supporting records. The reviewer verifies those records and their digests.
Primary and repeat supporting records must have distinct digests.

- Domain measurements identify the `domain`, exact `command` and `exit_code`.
  Complete suites require `scope: "complete"`, a positive `passed` count, and
  zero `failed`, `skipped` and `errors`. Dependency and vulnerability checks
  require a positive `components` count, `inventory_sha256` and an empty
  `unresolved` list. Dependency reviews require `inventory_complete: true`.
  Vulnerability reviews require `scan_complete: true` and `advisory_revision`.
- Journey measurements identify the `journey`, `locale`, `case`, durable
  `product_operation_ids`, and matching `expected_outcome` and `outcome`.
- View measurements identify the `locale`, `theme`, `viewport`, `check` and
  zero `failures`. Supply the relevant observation IDs in `keyboard_paths`,
  `geometry_samples`, `accessibility_checks`, `access_change_cases`,
  `first_frame_samples`, `page_read_keys` or `capture_ids`, respectively.
  Phone-sized viewport checks include the measured `inner_width` and
  `inner_height`.
- Physical phone measurements require `physical_device: true`, `device_model`,
  both `locales` and observed `journey_ids`. Feature coverage maps each
  feature ID from F1 through F64 to its evidence digest in `features`.
- Load measurements include `dataset`, `connection`, `durations_ms`, `errors`
  and `p95_limit_ms` for each run.
- Owner measurements identify the `responsibility` and measured `finding`
  for each run alongside the separate named explanation.

A rehearsal summary alone leaves certification deferred.
Both certification summaries must include exactly one passed row for each
scenario from the reviewed revision. This includes the baseline, release build,
all nine domain restarts and the web restart, acknowledged command, rollback,
restore and final reconciliation. Each restart must identify the candidate
artifact and a measured process transition.
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
immutable build, artifact reference and independent repeat against the same
sealed archive. Copied screenshots and outside benchmarks do not establish a pass.
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

Run the private whole-stack entry below from the repository root on beirut-test-1.

The default mode is rehearsal. The driver writes a private
`RUN/scenarios/e09/summary.json`, including scenario identifiers, operation
identifiers, source revision, measured seconds, outcomes and the five owner
responsibilities. Exit zero requires every connected case. Run output belongs
outside the source checkout. Rehearsal stdout contains only the outcome state.
Product operation and custody references stay in the mode-0600 summary.
An interruption or stack cleanup failure leaves measured scenario rows in that
summary and adds a separate failure row. The recovery and rollback cases each
require the previous Orders start's PID and start identity to match the process
they replaced.
The driver does not install dependencies.

The driver consumes private `RUN/native-v1.json`, version 1, using each
`services.<service>.env` dictionary directly. Restricted runtime database URLs,
routing and scoped signing values are preserved. Owner and migration settings
are removed from children. The web build and process receive only public
listener, origin, application mode and domain API routing settings, along with
the locally constructed execution environment. Release module and
contract paths are rebound; database URLs are never regenerated or substituted.
Settings and child output are never printed.

The private stack must be launched in a fresh network namespace containing its
own database and local simulators. `e09_host_network_namespace` records the outer
network namespace identity before entry. The driver rejects that identity and
non-loopback routes before launching children. Namespace creation and the outer
lifetime bound come from the stage. The launcher provisions the
private database.

The driver owns only children it launches. It retains process handles, start
identities, sessions and output readers. Replacement validates settings before
locking and checks namespace isolation, the release artifact and the invocation
before stopping the owned process. It holds the session leader unreaped through any signal escalation,
waits for readiness and retains the previous release invocation. Rollback replays
the captured arguments and environment. A failed launch also replays the saved
invocation. Exit and
termination clean up owned children. Existing stack ledgers confer no ownership.

`e09_prior` must describe a distinct compatible prior release with version 1,
`compatible: true`, `source_revision`, `root`, `artifact`, `config_hash`,
`schema_hash`, `schema_file`, `files`, `provenance_file` and `provenance_hash`. The root must be mounted read-only.
`files` inventories every regular file in the release, including application code,
compiled web output, contracts and installed dependencies. Symlinks and special
files are rejected; offline dependencies must be materialized inside the immutable
release. Missing or extra files fail validation. Prior Python services and
the first-operator command use the inventoried executable
`runtime/bin/python3` with its standalone standard library under
`runtime/` and application dependencies in `runtime/site-packages/`.
The interpreter runs in isolated mode with automatic site imports disabled.
The entry checks that the interpreter prefix and initial import paths are
within the reviewed runtime, then adds the release's service, contract and
dependency paths explicitly. Startup uses the prior release's inventoried
`scripts/native-services.json` for its service factories. The manifest hash
is bound by the reviewed inventory, and startup validates that the prior and
candidate service names and listener ports match the private routing. The reviewed configuration hash includes the
release-relative runtime binary directory in PATH. Each relative filename maps to
its SHA-256 hash; the artifact hash is
SHA-256 over sorted filename, zero byte, file hash and newline records. The schema
file must occur in that map. The configuration hash covers the normalized initial
service environments serialized as sorted-key JSON using `config_digest`.
Release and run path prefixes become `{release}/` and `{run}/`. The database
entry contains scheme, user, host, port and database path. Scoped credential
entries contain only `{"runtime_credential": true}`. Startup checks supplied
runtime values separately, including private signing key parsing and payment
secret length. `provenance_file` names a separately mounted read-only review record outside the
release; `provenance_hash` pins its exact bytes with SHA-256. The stage supplies
this record from the reviewed release input, never generates approval from the
candidate during the rehearsal. Its version 1 object has `schema_version: 1`,
nonempty `reviewed_by`, `compatible: true`, and identical `source_revision`,
`artifact`, `config_hash`, `schema_hash` and complete `files` values. This binds
review approval to compiled output and dependency bytes as well as source.

The source revision must be a full commit identifier available in local history
and an ancestor of the current revision. Every tracked file must match that
commit's blob bytes and be a regular file. At least one executable source or
configuration file under services, packages, web, contracts, scripts or infra
must differ from the current revision. Relabeling current source as an older
commit fails even with a newly calculated inventory. No network lookup occurs.
Bootstrap provisions the candidate migration ledger before either release
serves requests. The launcher derives both expected ledgers from their
release migration inventories. It requires every prior step and checksum
to be in the candidate ledger and verifies the complete live ledger through
each restricted runtime connection. A candidate process must pass the
standard readiness endpoint. When the candidate adds migrations, the launcher
starts the prior factory with an E09 readiness route. The route acquires a
connection from the running application's own pool and requires the complete
candidate ledger. The launcher also independently checks that ledger through
the restricted runtime connection. The same check applies when
Orders returns to the prior release. Both transitions preserve the ledger and
schema. The separate compatibility review and the live authority and held-fund
checks remain required. A second current revision is rejected.

Orders rollback uses verified release artifact IDs to distinguish the running
candidate and the reviewed prior release. Each Orders fingerprint covers the selected
Orders factory and the release-relative paths and contents of tracked Orders
runtime and module Python sources and module manifests. Tests, migrations,
generated files and runtime packaging are outside this comparison. The worker
measures the prior inputs after inventory verification and the candidate inputs
before sealing the archive. Replacement and rollback
record both fingerprints alongside the release artifact IDs. Rollback evidence
requires the fingerprints to match their respective releases in both transitions.
Identical Orders-local fingerprints are valid when the verified releases differ.

Build exports the source revision into a private release directory, packages the
contracts, compiles all nine domains and builds the production web with installed
local dependencies. Web and workspace packages resolve workspace dependencies
through relative links to the exported packages. Third-party links also stay
inside the release root. The launcher binds the installed offline store
read-only at `node_modules/.pnpm` inside that root during the production build
and at candidate process startup. Store links to workspace packages then
resolve to the exported release. The archive retains the relative links and
an empty store mount point.
The worker seals a release archive in memory before hashing it, removes the
writable build tree and keeps its sealed descriptor until cleanup. Each current
service start extracts that image into a private memory filesystem and starts
the process with the release mounted read-only. The stage must permit nested
mount namespaces and budget memory for these mounts. The stage must keep the
installed store, configured interpreter and its dependency directories on
immutable read-only mounts throughout the run. Use the same system runtime
base for primary and repeat. The configured `python` must name an absolute
virtual-environment executable under its `bin` directory. Candidate services
use isolated Python startup with automatic site imports disabled and add the
measured site-packages directory and exported application paths explicitly.
The archive header binds a SHA-256 fingerprint of the store's bytes and links,
the Python executable, virtual-environment configuration, standard library,
site-packages and the web runtime executable.

For the independent repeat, use a fresh private RUN and the same launcher
command. Mount the original `candidate.tar` read-only outside the new RUN and
add `e09_candidate` to the repeat's private `native-v1.json`. This version 1
object has exactly `schema_version: 1`, `archive` (the absolute mount path of
the mode-0400 file), and `sha256` (the primary summary's `build_id`). Keep the
same in-namespace RUN path and read-only dependency paths across invocations.
The release path inside RUN is `scenarios/e09/releases/candidate` in both runs.

The repeat verifies the archive digest and embedded source revision, then
remeasures the external application runtime against the archive's fingerprint
before registering the sealed bytes for replacement. A different runtime
fails with `repeat-release-runtime-hash` even when its mount paths match. It computes the Orders fingerprint from those
bytes and uses them for every candidate start without rebuilding or publishing
a second archive. Verification failure fails the release-build case. Its
summary records `archive_mode: "reused"` on the release-build row. The primary
summary records `archive_mode: "built"`. Certification requires these modes in
primary and repeat order, alongside separate run IDs and the same archive digest.

On a successful primary build the worker atomically publishes the exact sealed bytes as
`RUN/scenarios/e09/candidate.tar`, with mode 0400. The handoff is limited to one
archive of at most 1 GiB per RUN and survives process cleanup. Keep RUN private
and retain it for the independent reviewer. The reviewer hashes the archive with
`sha256sum "$RUN/scenarios/e09/candidate.tar"` and compares the digest to
`build_id` in that invocation's private summary. After checking the archive and
recording the result, remove it with `rm -- "$RUN/scenarios/e09/candidate.tar"`.
The stage must reclaim the private RUN within 24 hours if review does not finish,
including any partial handoff left by forced termination.

Execution requires a network namespace with only loopback routes; missing isolation
is a named failure before any build command. The local simulators remain selected
by the runtime settings. No remote provider is allowed.

Authoritative reads use the owned Orders process's restricted database URL.
Each snapshot uses a bounded read-only query against Orders. No additional HTTP
read bindings are required. The callback event ID identifies the operation and
its durable callback receipt in `l13_payment_callbacks`. The Communications
consumer inbox is measured separately through its restricted runtime database.
The snapshot matches the confirmed payment's Orders outbox event ID and source
to a durable Communications inbox entry for `communications-order-timeline`.
Checkout notice acknowledgements
predate confirmation and are excluded. The current release registers the
confirmation destination as pending. Each emitted payment-confirmed event must
have a durable receipt with the matching event ID and Orders source. If the
receipts are still missing after the bounded wait, the case fails with
`communications-payment-confirmed-delivery`. Connected proof requires delivery
through the enabled product destination and its Communications receiver. Only payments whose
order and associated inventory are both marked non-demo enter the snapshot. It joins
the payment attempt and current order to the authoritative retained quote by
order, quote and quote revision. The comparison includes the full quote snapshot,
so fee, commission, shipping or tax changes fail even when the payable total
stays fixed. It checks for refund, release or reconciliation
state, and reads the journal posting and its balanced entries. It reads the
payment-confirmed outbox records by journal group and the Orders intake records
by order. Outbox delivery bookkeeping may advance independently of the retained
event. Each intake fact must have exactly one successful durable command record
matching the receipt ID, actor and revision. Reconciliation retains both records.
Missing journal, custody or outbox coverage fails reconciliation.

The required `e09_command` supplies a confirmed signed simulated payment callback
`body` and optional scoped `headers`. Its `event_id` is the product reference.
Bind the body to the pending attempt returned by the Orders journey. Use its
order, buyer, quote, quote revision, currency, total, route and simulator
reference, with the next sequence. The baseline payment must belong to a
different order. The driver checks those facts before sending, signs the
exact bytes using the Orders runtime payment secret and posts to
`/callbacks/v1/simulated`. This handler creates the balanced held-funds journal;
a notification acknowledgement cannot substitute for it. The driver sends the callback and keeps the connection open until it observes
the durable receipt. It then closes the connection without reading the response,
replaces its owned Orders process and retries identical bytes. Recovery requires a successful
Orders transition to the candidate first, and records the candidate artifact
on both sides of the retry restart. The retry must report a
successful, confirmed and currently paid result for the same order and attempt.
Receipt, journal, custody,
inbox and outbox rows must remain identical for that reference, with one journal
effect. The launcher still restarts and retries an acknowledged callback if
the bounded pre-restart inbox wait expires. The case fails unless a durable inbox
receipt is present both before and after the restart. For each successful snapshot, the summary retains payment callback references in
`product_operation_ids`, intake fact IDs in `custody_receipt_ids`, and
durable intake command IDs in `custody_operation_ids`. The recovery step
also identifies the retried callback in `recovered_callback_ids`. The worker first queries the durable confirmed callback by event, attempt and
order before reading the wider reconciliation records. Once the
callback receipt is observed, the summary retains its reference in
`acknowledged_callback_ids` even if restart, retry or reconciliation fails.
The backup handoff includes this reference regardless of the recovery outcome.
The launcher also measures durable baseline callback IDs separately from the
inbox and wider financial reads. On interruption during the baseline journey,
the launcher reads committed callback IDs before stopping the stack and preserves
the interrupted outcome. These IDs remain in the private summary and, when the
rehearsal continues to restore, in the backup request. After durable acknowledgement
of the dropped-response command, an incomplete pre-restart observation still
allows the owned restart and identical retry. The case remains failed when
that evidence is incomplete.
For both the baseline and the dropped-response command, each inbox poll checks
the payment, journal, custody and outbox records against the first durable
snapshot. Rehearsal
request IDs stay in `operation_ids`.
A missing command or missing durable product records fails the case.

The result binds measured build, rollback, restore and reconciliation scenarios
to release check IDs in `provider_evidence`. The certification checker reports
outstanding independent repeats and all other missing proofs in `remaining_proof`,
including when startup fails before any case runs. Responsibility
labels do not establish five named explanations or an independent repeat. The
nine-domain suites, dependency records, 64-feature coverage, bilingual views,
physical phone, load, live prior-version compatibility and connected restore
remain separately owed. Local checks prove behavior only; the designated-host
rehearsal is still required.

`E09_MODE=railway` with the same entry point prints only the proposed commands
and exits without reading settings, writing evidence, building or executing any
command. It never deploys.

## Private whole-stack entry

Inside the stage's bounded private namespace, invoke exactly:

```
E09_MODE=rehearsal python tests/lanes/L22/E09/launcher.py --run-dir "$RUN"
```

This entry owns PostgreSQL 17 and all ten application processes in the same
worker lifetime. It uses the same native-v1 service environments, prior release,
read and command contracts described above. Run it with a non-root effective
user ID. The namespace must already have
loopback enabled, offline dependencies and current and prior releases mounted
read-only, no host sockets or remote routes, and only RUN and scratch writable.
Mount the prior root outside RUN and expose RUN at one path only. The launcher
gives each application and the web build a private PID and mount view with fresh
`/proc` and `/dev` and an empty mount over RUN. The web build sees its own writable
release tree. Each current application sees only its own read-only release
extraction at that path. Provisioning files, database files and sibling process
environments are outside these application views.
The launcher does not grant permission to reuse any existing stack or cluster.
The stage must bound the entire namespace lifetime, including forced termination.

Add `e09_database` version 1 with `schema_version: 1`, `bootstrap_sql` and
`authentication_file`, both private files inside RUN. Bootstrap SQL provisions
fresh restricted runtime roles matching the supplied service URLs and applies
the candidate schema migrations to empty databases. It must not insert business transactions.
Before starting the prior release, the launcher checks the nine runtime
databases through the private provisioning socket. Each domain must have a
distinct database and login role. The login must have access only to its
assigned database and have no elevated role attributes, memberships, ownership,
or database or schema creation privileges. Any existing application
rows fail startup. Only the migration ledger and Catalog's search alias
dictionary may contain provisioning rows.
Owner credentials are confined to provisioning; children receive normalized
runtime environments only. Authentication contains only loopback `host` records
using `scram-sha-256`, plus comments or blank lines. The launcher supplies the
local provisioning rule itself, initializes RUN/e09-database as UTF-8, starts PostgreSQL on port 54329 with
its provisioning socket in RUN/e09-database-socket, and applies bootstrap with
error-stop semantics. Each PostgreSQL instance runs in a private PID namespace with its own writable
shared-memory mount at `/dev/shm`. The launcher
holds a pidfd for the namespace init before allowing database initialization.
The same namespace contains initialization subprocesses and the running server.
The launcher waits for namespace exit before reclaiming database files. It installs authentication
and requests a reload over the provisioning socket before starting the prior release. Before that reload it replaces
local authentication with `local all all reject` and prepends explicit loopback
owner rejection rules ahead of runtime rules. It waits until a new owner socket
connection is rejected by the authentication rules; unrelated connection errors
or an unobserved reload fail startup. No provisioning connection survives into
application startup. Missing prior compatibility or
provider reads still fails; empty databases never satisfy connected recovery.

The worker retains every process handle and drains private child output without
publishing it. Summary output remains RUN/scenarios/e09/summary.json.
Startup command timeouts and unsuccessful exits record a named failure in the
private summary and emit only the failed outcome to stdout. Normal exit,
TERM and the bounded worker timeout stop owned application groups before the
database and reclaim the owned cluster. The launcher claims the cluster directory
atomically. If the directory already exists or another invocation claims it
first, startup fails and leaves that directory intact. Namespace-level
forced-exit cleanup remains the stage's duty.
Reclamation errors fail the run. The launcher retains ownership until it has
removed both the cluster and its provisioning socket directory.

As part of the baseline case, the launcher executes required `e09_journey`, an ordered
array of at most 128 product steps. Each request has a unique `id`,
`service` (one domain), `path` (an array of literal segments or result references),
`body`, optional scoped `headers`, and nonempty `expect`. Requests use POST to
that domain's manifest port and a `/v1/` path. For the Catalog
`/v1/seller/listings/<listing_id>/media` step, supply `photo_file` in place
of `body`. Give a relative path to a public-safe watch image under RUN.
The launcher sends up to 8,000,000 raw bytes with `X-Media-Kind: public_photo`
and `X-Public-Safe: true`. Supply the seller authorization, current listing
revision in `If-Match` and a stable `Idempotency-Key`. The publish step can
reference the returned `listing/revision`. Each response is bounded to one MiB;
non-success HTTP status or an unmet expectation aborts startup and cleans up.
`expect` maps slash-separated response object keys to required values, such as
`{"status": "succeeded"}`. Responses remain private in memory.

A value `{"$result": "create-order/order/id"}` resolves a prior request's actual
response field. References work recursively in bodies and headers, and as path
segments. A protected request can use
`{"Authorization": {"$bearer": "buyer"}}` where `buyer` identifies a successful
Identity registration step. The worker sends that account's returned access
token with the Bearer scheme. The callback body uses the same mechanism. Preserve explicit product
idempotency keys in request headers; rehearsal step identifiers are never used
as product references.

Before placing an order, verify the buyer's contact through Identity's local
contact simulator. Enable `BT_CONTACT_SIMULATOR=1` in Identity's service environment.
Use the buyer's reauthentication proof to create a contact challenge. If the
challenge step is named `buyer-challenge`, follow it with these steps for email
verification.

```json
[
  {
    "id": "buyer-contact-code",
    "contact_challenge": {"$result": "buyer-challenge"},
    "participant": "buyer"
  },
  {
    "id": "verify-buyer-contact",
    "service": "identity",
    "path": ["/v1/contacts/challenges/", {"$result": "buyer-challenge/id"}, "/verify"],
    "headers": {
      "Authorization": {"$bearer": "buyer"},
      "Idempotency-Key": "buyer-contact-verification"
    },
    "body": {"code": {"$contact_code": "buyer-contact-code"}},
    "expect": {"email_verified": true}
  }
]
```

The read uses the registered buyer's session and the challenge returned by
Identity. The code stays in memory and can be used once for verification of
that challenge by the same participant. The summary excludes the code.

Before each payment attempt, add a checkout wait step such as
`{"id":"payable-order","wait_for_payable":true,"path":["/v1/orders/",{"$result":"create-order/order/id"},"/checkout"],"headers":{"Authorization":{"$bearer":"buyer"}}}`.
It polls the authenticated Orders checkout for up to 30 seconds and records the
response when buyer notification has opened a payable window. Set the payment
attempt body's `expected_revision` to `{"$result":"payable-order/order/revision"}`
and preserve the attempt's own idempotency key.

After registering the operator, add
`{"id":"grant-first-operator","first_operator":"operator","reason":"Authorize the initial rehearsal operator"}`
where `operator` is the registration step ID. The launcher invokes Identity's
first-operator command from the running prior release with its scoped runtime
settings, verifies the returned subject, and refreshes that account's session
before subsequent requests. The grant uses Identity's one-time seal and audit.
The native Orders payment route checks the retained recovery assignment. Use
the ordinary product journey to establish that authority once Orders exposes a
supported command for newly created orders. Keep the buyer authorization and
stable idempotency key on the payment attempt. The current release returns
`recovery_assignment_unavailable` for a payable order with no assignment. The
launcher records `orders-payment-recovery-assignment-command` in this case.
The baseline fails and connected payment proof remains owed until the Orders
command is available. The release build and service replacement cases still
run and record their own outcomes.

For Catalog and Orders requests that act on behalf of a business, add
`"organization_id":{"$result":"onboard-business/id"}` to the request object.
The resolved UUID must come from an active, non-sample Identity onboarding
response in this journey. The launcher sends it as the single
`organization_id` query parameter. Identity still establishes the participant's
business permissions, and Catalog and Orders check them on each request.

The supplied journey must register and authorize participants, create and commit
real inventory and quotes, place orders, establish actual custody through its
product commands, and start payment attempts. It must confirm at least one
baseline order through the approved local payment simulator, while leaving a
second valid attempt for the dropped-response confirmed callback. Use the Orders intake route for custody and its scoped authorization. The
stable callback event reference remains the payment operation ID. The payment
and intake commands retain their own separate identities. Missing product
records fail the connected case. Bootstrap SQL still provisions roles and schema only.

Reconciliation compares baseline and recovered-command receipts, journal,
custody, inbox and outbox with live reads after rollback and with direct reads
of the isolated restored database. Both checks verify that funds remain held
for each acknowledged payment and that each payment still has one journal
effect. Release reconciliation evidence requires both checks and the final
live reconciliation to pass.

### Retained restore input and current authority

After the baseline and dropped-response command have been acknowledged, the
launcher invokes the E04 producer against the owned cluster on port 54329:

```
python tests/lanes/L24/E04/retained.py --run-dir "$RUN" --output-dir "$RUN/e04-backup"
```

The launcher resolves the producer in the current source and runs it from RUN
with the configured interpreter and PostgreSQL 17 binaries. Both producer invocations receive one JSON object on stdin with
`schema_version: 1`, the current `source_revision`, and
`required_operation_ids` keyed by all nine domains. The launcher reads
the complete acknowledged records from each restricted runtime database before
capture and supplies their distinct operation IDs. Orders must include the
baseline and recovered payment event references. The producer must report
the same IDs per domain. The producer reads the private native-v1 settings and uses
scoped backup access to this cluster. The launcher reserves the private output
directory and rejects one left over from another invocation. Descriptors use
mode 0600.

1. The launcher measures the live deletion and revocation rows using the
   reviewed domain queries. It sends `phase: "capture"` and
   `backup_watermarks` containing those measurements as hashes. The producer
   retains nine custom dumps and writes `capture.json` with the root, revision,
   dump paths and hashes, per-domain schema revisions and acknowledged
   operation IDs, and its observed `backup_watermarks`. The launcher hashes
   the dumps and checks that the live watermark point held through capture.
2. The launcher runs a separate required `e09_watermark_journey`, using the same
   request and result-reference format and existing participants. It accepts
   POST and explicit `method: "DELETE"`. Supply real deletion and revocation
   product commands for subjects independent of the payment and authority
   probes. The commands must advance both measured watermark categories while
   leaving acknowledged payment, custody and inbox records intact. For
   Authorization headers, use a registered participant's `$bearer` reference.
   The launcher refreshes that participant immediately before sending the command.
3. The launcher remeasures the live watermarks and sends `phase: "finalize"`,
   `capture_reference` (the canonical SHA-256 of `capture.json`), and the
   measured `current_watermarks`. The producer writes `handoff.json` with
   watermark statements for the retained dumps and binds the exact capture
   reference and both watermark points. The launcher verifies the dump hashes,
   paths, schema revisions and acknowledged IDs again before restore.

Each watermark point maps domain to `deletions` and `revocations` digests.
A digest is the canonical SHA-256 of a sorted array of serialized rows with
duplicates retained. Serialize each row with Python's
`json.dumps(row, sort_keys=True)`. For the outer array and descriptors, use
UTF-8 JSON with sorted keys, ASCII escaping and compact separators.

An absent producer fails with `E04-connected-backup-output`. E04's existing
isolated restore runner does not publish the two-phase handoff. Its connected
producer proof remains owed.

The returned version 1 handoff contains `schema_version: 1`,
`root` equal to RUN/e04-backup (a private directory), `source_revision`,
`schema_revision`, `capture_reference`, `watermark_points` (containing
`backup` and `current`), and `domains` keyed by all nine domain names. Each domain has
`dump`, `dump_sha256`, `watermarks`, `watermarks_sha256`, `schema_revision`,
and nonempty actual `operation_ids`. The top-level `schema_revision` is the
SHA-256 of the domain-to-schema-revision map serialized as UTF-8 JSON with
sorted keys, ASCII escaping and compact separators. Each domain revision is
also compared to the live and restored schema reads. The summary's
`backup_reference` is the SHA-256 of the object containing `schema_version`,
`source_revision`, `schema_revision`, `capture_reference`, `watermark_points`
and `domains` in the same encoding.
This binds the reference to the verified dump and watermark hashes, schema
revisions and acknowledged operation IDs after cleanup. Filenames are relative
regular files beneath the handoff root. Dumps use the custom database format. The pinned
watermark file contains one UTF-8 SQL mutation statement for the restored
database's public tables. Use a data-modifying common table expression when
several changes must be applied together. The consumer sends the statement
over the extended query protocol in a bounded transaction, using a restricted
role and the disposable cluster's private socket. The producer must snapshot
acknowledged references and current
watermarks from the product; preparation summaries are not handoffs.

The reviewed prior release inventory must include `recovery/domain-reads-v1.json`.
This separately reviewed file maps each of the nine domain names to its pinned
measurement queries. SQL in a handoff's `queries` field fails validation.
Each domain has exactly `operations`, `deletions`, `revocations`, and `schema`.
Each value is a read-only SELECT returning durable complete records; operations
include `operation_id` and all retained economics and custody facts, watermark
queries include current durable identities and positions, and schema returns
one `revision` column. Before applying any watermark statement, the consumer
compares the complete acknowledged records in all nine restored databases
against the independently measured live records from before capture, including
duplicate rows, and verifies the payment, custody, journal, inbox and outbox
records. Before granting replay write access, it also compares every restored
schema revision with the captured revision and an independent live schema read.
It repeats the comparison after replay.
Replay must preserve those records and the full contents and multiplicity of
the acknowledged operation rows. The consumer runs each reviewed query
against both the current restricted runtime database and the restored
database after replay. Results must match as multisets. Each restored domain must match the captured watermark
digests before application and the measured current digests afterwards. Each
watermark category requires a measured change to a nonempty state that matches
the live records in at least one domain.
Individual domains can return empty results for a category. Operations
and schema must be nonempty, schema must match the pinned revision, and every
acknowledged reference must exist. PostgreSQL 17 restores use a disposable
socket-only cluster on port 55439 with UTF-8 destination databases. If a
restore measurement detects missing acknowledged references, the failed
restore row retains the measured IDs in the private summary under
`lost_acknowledged_operations` and the rehearsal exits nonzero.
The payment, inbox, journal, outbox and intake projection also runs against
restored Orders and Communications and must match the live snapshot. The same supervisor holds a pidfd for the restore namespace init before
allowing database initialization. It waits for namespace exit before reclaiming
scratch, including after interruption, timeout or readiness failure. The
namespace covers PostgreSQL backends in separate process groups. Scratch
remains available for stage cleanup if the supervisor cannot confirm exit. The launcher also owns handoff cleanup, including partial output
when the producer fails or the rehearsal is interrupted. Live execution remains
owed until the producer supplies these files.

`e09_authority` contains `allowed` and `denied` probes. Each contains `path`
segments, scoped `headers`, and nonempty response `expect` fields using the
journey result-reference format. Both issue GET requests to Orders after the
prior version is ready: the authorized participant must receive 200 and the
unauthorized participant 403, with the expected product outcome fields. Both
probes must use the same detail or checkout path for the order tied to the
durable callback receipt for the dropped-response command. Use the registration-based
`$bearer` header for two distinct returned account IDs. The worker retains
each registration's refresh cookie and origin privately, refreshes each session
through Identity just before its probe, and checks that the refreshed account
matches the registered account. A missing probe or incorrect permission outcome
fails rollback. Final durable reconciliation requires exact counts of complete
records for baseline and recovered operation IDs, including inbox and outbox
records. New records for unrelated operations can appear.
