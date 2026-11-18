# Auction recovery proof preparation

This additive module prepares a versioned observation contract, operation lookup,
synthetic fixtures and a bounded runner. It changes no runtime composition.
No measured load, connected recovery, notice delivery or winner claim follows
from its unit tests. Synthetic fixtures do not seed accepted business records.

`contract.py` publishes the schema, current operation paths, dataset, private
retry binding and required cases. `test_harness.py` provides deterministic
success, denied, stale, duplicate, timeout and lost-response result fixtures.
`harness.py` validates complete observations and returns a serializable manifest
with exact results and remaining proof. Write any run output outside the source
checkout. Never include credentials, tokens, private ceilings, evidence references,
request bodies, actor identities or private responses in output.

## Short preparation check

Run from the repository root:

```
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/lanes/L14/A10/test_harness.py
python -m ruff check tests/lanes/L14/A10
```

## Separate-machine adapter contract

The native provider below supplies a partial connected implementation. For a
separate implementation, after explicit separate-release clearance, call
`await run(provider, clearance=True, connected=True, connection=description)`.
The non-private description states the dataset connection and network conditions.
Without the connected flag the result is always synthetic preparation, and every
connected case remains owed. Clearance is an explicit caller responsibility;
it is never inferred from an environment variable or dependency availability.

Use two independent local auction processes sharing the real canonical durable
store. Run 50 viewers separately from 200 distinct bidders. Route concurrent
commands across both replicas; do not serialize clients to manufacture ordering.
Bidder participant numbers identify clients, never admission order. Acquire real
current identity, business membership, record scope, revision, accepted terms and
retained quote facts. Never use a projection as authority. Use integer USD cents
and authoritative UTC time, retaining the original scheduled end.

Each `run_load` is bounded to 60 seconds; each request to 5 seconds and at most
3 attempts, retaining the same operation reference through uncertainty. Reject
unbounded payloads. History pages contain at most 100 rows, use the returned
sequence cursor and stop at the measured canonical sequence within the time
budget. No cross-service database reads are permitted.

Viewer latency starts at successful serialized admission and ends at each
viewer's observed update, on each replica. Use one monotonic clock for intervals,
not comparisons between unsynchronized host clocks. Return all 100 viewer/replica
pairs, including errors. Keep rendering evidence separate if only reads are
measured. For notices, the 200 samples run from each corresponding event's durable
commit to required notice availability in its recipient's durable inbox, not to
send attempts. Every bidder supplies one result; measure bid completion latency
and errors without inventing a bidder latency target. Expected business denials
must also be counted and explained by the adapter, never dropped as slow samples.
Report nearest-rank p50/p95 and errors. The viewer target is 2 seconds and notice
target 30 seconds; this harness conservatively requires every sample within its
target. A slow or missing sample fails the target rather than claiming success.

`exercise` must perform each named scenario on fresh synthetic stock and raise
if its observed durable assertions fail. `CaseResult.invariants` names assertions
actually executed, never seeded success. Revoke access after an earlier read;
retry stale, denied, timeout and duplicate cases against real providers. Bind
operation lookups to the owner, business, watch, exact command and quote revision.
At the end boundary, establish server time before/equal/after the fixed end,
not a browser countdown. The before case must demonstrate an accepted bid.

Kill one replica or stream after acknowledgement, poll the surviving replica,
restart the missing process and compare ordered gap-free replay plus snapshots.
Restart the canonical worker after durable acknowledgement and before its next
step; all acknowledged bids and their original sequences must survive. Crash the
notice path after inbox commit but before relay acknowledgement; replay the same
event and verify one required notice per recipient/event. Exercise immediately
beaten challengers as well as displaced holders. Restart closing/allocation after
its durable result but before response; verify one winner, one order and one
physical-watch commitment through owner APIs. Unknown allocation remains pending;
no alternate winner or timer release is acceptable. Public history and events
must exclude private ceilings and honor full-step v2 competition.

## Deferred acceptance

A07, A08, NOTICE and KERNEL connected adapters and their positive, negative,
permission, timeout, restart and recovery journeys remain required. The runner's
case assertions cannot establish these facts without those adapters. Heavy
50-viewer/200-bidder execution, real durable shared-store contention, worker and
replica process termination, outbox replay and 2-second/30-second measurements
remain separate-machine work after clearance. Missing operations stay deferred;
fixtures never replace connected acceptance.

No page changes are included. EN/AR, RTL, themes, keyboard, actual 390 by 844
viewport with `window.innerWidth === 390`, screenshots and physical-phone feel
remain owed wherever the connected viewer journey is claimed. Read visibility
alone must never be reported as completed rendered-viewer acceptance.

## Native connected entry point

From the repository root, using the installed project environment:

```
python tests/lanes/L14/A10/run_native.py --run-dir "$RUN"
```

The command consumes the suite's private `RUN/native-v1.json` service environment
and existing `RUN/domain-contracts`. It launches one owned auction child on a free
loopback port with the auction runtime database settings unchanged. It never
stops the suite's original process. Child output is discarded so private runtime
settings cannot enter the summary. Requests disable environment proxy discovery
and redirects. No deployment or dependency installation occurs.

Provide `RUN/a10-input.json` with mode 0600. This private prerequisite contains
`seller` and `actors` (exactly 200 distinct buyer objects), each with
`email` and `password` from stage preparation. A10 uses the email to look up
the prepared session and leaves the password unused. `sessions` is an object
keyed by normalized email (trimmed and lowercase), with one entry for the seller
and each buyer. Each entry contains `subject_id` (the Identity account UUID) and
`refresh_cookie` (the value of the current `bt_refresh` cookie). The stage
prepares accounts and sessions through Identity's real flows under the existing
registration and sign-in limits. Buyers must already have verified sample
contacts and accepted current terms. `listings` maps scenario names to distinct
fresh, published sample listing ids owned by that seller:
`viewers`, `bidders`, `duplicate_command`, `stale_revision`,
`cross_account_lookup`, `replica_loss_poll_resync`,
`worker_restart_acknowledged_bids`, `before_end`, `equal_end`, `after_end`,
`revoked_identity`, `denied_scope`, `lost_response_same_operation`,
`timeout_pending`, `outbox_replay_duplicate_notice`,
`one_winner_allocation_restart`, and `private_maximum_redaction`.
The scope case also requires `scope_organization_id`, a current organization
represented by the seller; the current principal read verifies that membership
before an organization-scoped bid must be refused. Missing prerequisites produce
named failures. Stock and the input file must remain exclusive to one run.

A10 refreshes each prepared session through Identity and checks the current
account against the supplied subject and email. It also reads current contact
verification for each buyer. It repeats those checks when renewing access during
a run. The preparation timeout is 4500 seconds.

Before sending a refresh, A10 atomically clears that entry's cookie in the
private input file. On rotation it atomically checkpoints the successor with mode
0600 before the current reads. Each session is refreshed under its own lock.
An ambiguous refresh, interruption before the successor is saved, or rejected
cookie leaves a null cookie and requires the stage to provide a current session
for the affected account before a rerun. Use the checkpointed file on resume.
The revocation case runs last and consumes the final buyer's session. Replenish
that session through stage preparation before rerunning after revocation.

The bidder auction uses a ten-minute fixed deadline. The owned process (including
its workers) restarts halfway through acknowledged load. Recovery checks all 200
receipts by their retained keys on both replicas, exact ordered history, and the
real close worker's final winner and price, then restarts again and compares the
durable result and history. Load is bounded to 480 seconds and recovery to 1600.

The command writes `RUN/scenarios/a10/summary.json`, never a repository artifact.
Every required scenario has `state`, `operation_ids`, `measured_seconds`, and
`source_revision`. Missing capabilities are named and exit status is nonzero;
zero requires every connected case to pass. Exception messages, actor identities,
credentials, request bodies and private responses are excluded. Source revision
is the current commit; run from a clean candidate checkout for release proof.

Viewer observations cover all 50 signed-in readers through the gateway, with additional reads on each real replica after admission.
The measured interval starts before submission, conservatively including request
latency; it proves read visibility only. Bidder commands alternate between the gateway and the owned writer, retain their keys across transport retries, and count business
denials as failures. Up to eight buyers contend concurrently. A durable stale-revision denial
starts a new command with a fresh snapshot, quote, review and key; transport
retries preserve the submitted body and key. Other business denials fail the case. Request completion order
is never used as canonical bid order. Recovery reads verify ordered history and
snapshots from both database-backed processes after terminating the owned child.

The equality journey reads the seller-private deadline boundary, which evaluates
the production admission window rule at the stored deadline. It then submits a
real bid after the authoritative clock reaches that deadline and verifies denial
and empty history on both replicas. The boundary read is a policy evaluation;
it does not claim an HTTP request arrived at an exact timestamp.
The pending journey holds the real Orders commitment response, reads the retained
pending operation and empty history, then releases and retries the identical key
and body. The relay journey suspends the owned process after real event ingestion,
waits for the recipient's durable Inbox binding, kills that process and replays
the captured authenticated event unchanged. The allocation journey suspends and
kills the owned process after Orders has committed the allocation but before
Auction can acknowledge it; recovery compares the winner, order and physical
watch binding. These controls change transport and process lifetime only.
They never insert or update domain rows. If another process claims a delivery
before the owned process, the required interruption is unobserved and the case
fails; an ordinary successful delivery cannot count as crash proof.
The scope, revocation, post-commit response-loss, after-end, and full-step v2
journeys issue real requests and require connected execution. No local unit
result establishes connected acceptance. Rendered-viewer acceptance also remains
deferred. Commands reach both writers; the owned writer restarts after its own
acknowledged mutations. Recovery compares both replicas' receipts and snapshots,
then the winner's order and the physical watch's retained availability binding.

Focused checks, without a running stack:

```
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/lanes/L14/A10
python -m ruff check tests/lanes/L14/A10
python -c "import ast,pathlib; ast.parse(pathlib.Path('tests/lanes/L14/A10/run_native.py').read_text())"
```

Notice timing observes each of the 200 admitted bidders through the authenticated
bid-notice gateway endpoint while load runs. The interval starts immediately
before bid submission and ends after the notice can be opened and its bound
record is visible in the public inbox, a conservative
upper bound on commit-to-visibility time. It includes polling and durable binding
checks rather than treating an event timestamp as a commit clock. The existing
30-second target applies to every measured upper bound. Authenticated owner receipt reads correlate the durable source event by auction
and accepted sequence with the recipient notice and committed Inbox identifier.
These reads use the owners directly on the local native ports and add no gateway
route. Missing observations or unavailable receipt bindings fail the scenario.
Participant request failures remain measured error samples; successful samples
retain their latency percentiles even when other participants fail.
