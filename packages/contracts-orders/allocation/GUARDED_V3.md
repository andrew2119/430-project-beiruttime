# Orders commitment v3

`guarded_v3.py` is the private command boundary. Job allocation must bind the
current request, assessment, consent, grant, accepted lines and terms explicitly.
The older `brand_job` allocation cannot establish these bindings and denies new
commands. Exact old operation receipts remain available under their original key.

Financial and custody commands bind the actor, selected business, physical watch,
order revision, source revision, retained quote and policy. Financial commands also
bind the immutable recipient, actual receipt and current incident/dispute revisions.
Amounts are integer USD cents. Private evidence never belongs in an event or lookup.

The allocation kernel calls current authority inside the caller's transaction.
Missing authority or a missing journal boundary returns pending, with a responsible
person and review time. Denial and stale revisions never mutate money or custody.
The one journal boundary must atomically reserve unresolved plus confirmed refunds
against retained refundable principal, exclude all fees, serialize release against
refunds and holds, and retain the original recipient through uncertain transfers.
Job fee receivables never reduce customer principal. Release requires paid held
funds, current inspection/assurance/quality, actual receipt, the entire accepted
72-hour private-sale or 168-hour business/job window, and no dispute or incident.
A custody boundary records an actual authorized handoff; dispatch alone is denied.
These producer checks are required, not facts inferred from the command body.

Operation lookup uses the existing Orders `operation` function with the authenticated
actor key and original operation key. The retained result describes that operation,
not current execution permission. Retries use exactly the same payload/key; changed
content conflicts. New current permission is checked even for receipt recovery.
Timeout or a lost response is pending; retry and lookup use the same key. No new
allocation, balance or journal is introduced. Runtime registration and binding of
the current authority, existing journal and custody boundary are separate work.
The module cannot authorize a transfer if these interfaces are absent.

`fixtures/guarded.v3.json` contains deterministic development outcomes, including
success, denied, stale and lost response. These are synthetic protocol examples,
never recorded payment, receipt or work evidence.

`GET /internal/v3/orders/{order_id}/commitment` locks the canonical order and
watch and reads the retained quote revision. Its `current` field compares the
actual source order and reserved watch state; a historical successful operation
cannot substitute for it. The response always denies payment authority.
`GET /internal/v3/orders/{order_id}/unpaid-release` reads an immutable receipt,
not current availability. Both reads require an authenticated permitted internal
consumer. Missing receipts are unavailable, never reconstructed with today's time.
Historical no-attempt recovery requires exactly one matching original release
audit at the retained revision and never changes the watch, order or notice clock.

A refund may bind a current recorded `pre_dispatch` cancellation or
`failure_exception` without inventing physical receipt. The authority producer
must verify that exception against current custody before reserving principal.
A `controlled_return` refund and every release require the actual receipt identity
and revision. Release cannot use a refund exception.

`jobs.allocate_job` locks the canonical physical watch, consumes the current typed
job decision, retains its complete immutable binding/economics and publishes the
required notice in the same transaction. Its expected revision is the watch's
revision before allocation. The producer verifies current identity, business,
assignment, accepted scope/assessment, independent reviews, consent and serialized
grant prepare/consume/revoke permission. A historic accepted quote alone cannot
supply that decision. First execution consumes permission; recovery checks access
without consuming a second grant. Missing, denied or timed-out authority does not
allocate; retry uses the original operation key. No notice timestamp is invented.
