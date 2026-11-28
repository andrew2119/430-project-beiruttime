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

No connected adapter is supplied or implied. After explicit separate-release
clearance, supply the `Provider` interface and call
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
