# Second sprint native execution

From the repository root, with the native stack already running and RUN set to
an external private run directory:

```sh
python tests/integration/sprint-2/connected_runner.py --run-dir "$RUN"
```

The gateway is fixed to the loopback production origin on port 3000. The command
reuses the first-sprint account registration, sign-in, operator bootstrap,
business onboarding, contact verification, sample publication, reservation and
directory steps. It never starts services, deploys or calls an external origin.
The private native-v1.json follows the first-sprint native configuration contract.
Payments use the approved local simulator. Run only one process per directory.

Evidence is written atomically with mode 0600 to scenarios/e06/summary.json
inside RUN. Each scenario has an identifier, passed or failed state, operation
identifiers, measured seconds and source revision. Exceptions, credentials and
private records are excluded. Exit status is zero only when all forty required
journey cases and every recorded setup step pass. Unit results never count as
connected proof. Live execution is deferred to the test server.

## Producer execution

The runner submits commands to the gateway and verifies durable producer reads.
A new operation reference is checked before delivery; its command is retained
privately before sending. An interrupted delivery reuses the original reference
and binding. If draft submission committed before its response was lost, the
runner replays the retained submission command, reads its immutable operation
receipt and restores that verified receipt before continuing. No input may supply a paid, winner, receipt, work or release outcome.
A successful request admission or assessment claim alone never passes a journey.

Customization continues through assessment, assessed quote issue and buyer
acceptance, consent, independent eligibility review, grant preparation, independent approval, canonical job allocation,
payment, business authorization, actual work observations, independent quality,
custody and release. Consent is recorded while the private draft is still open.
Service follows its own assessment and accepted scope, allocation and payment,
then the separate paid-service authorization contract, work, quality, custody and
release. Service quote acceptance, checkout and payment use the signed-in requester
retained at submission, including when the second buyer wins the purchase. Quote issue uses usd-job-v2; the existing purchase and auction use usd-v2.
Allocation must return the real order and its checkout must match the accepted
quote and total before payment begins.

Real physical observations and current private producer command inputs belong
in RUN/e06-inputs.json, mode 0600, with schema_version 1 and objects named
protected_purchase, paid_auction, customization and service. This is an input
contract for the native composition; it is never a result file. Each named step
has actor (a signed-in account alias), subject, body, and optionally producer
(one of the fixed producer names in connected_steps.py). The body uses the
published producer command schema. The runner supplies the stable operation_id
or operation_key and checks actor identity, response scope and immutable receipt.
Unknown producers and supplied outcome fields are refused.

An optional top-level actors object maps additional account aliases to business
(brand or dealer) and qualifications. These actors are registered and signed in
through the same account flow, then granted current memberships by the signed-in
operator. Use distinct qualified people for assessment, approval and quality.
No membership or qualification is inserted directly into storage.

Values may be typed references, for example:

```json
{"reference":"state.businesses.brand.id"}
```

References resolve through state (the private walkthrough state) and steps (the
journey's verified producer receipts). Integers remain integers. The quote entry
has actor and an IssueQuote body; the runner builds explicit AcceptQuote from the
current quote, checks accepted read-back and retains exact USD economics. The
required customization step names are assessment, consent, eligibility_review, eligibility, approval,
allocation, authorization, work, quality and custody. Service uses
service_assessment, scope, allocation, repair_authorization, work, quality and
custody. eligibility_review uses the eligibility decision producer with kind review
and verdict eligible, signed by the currently assigned independent reviewer.
eligibility uses kind prepare with the same consent_id and expected_revision
referencing steps.eligibility_review.revision. Each command retains its own
operation reference and verified receipt. The owning runtime enforces reviewer
assignment and independence. Input observations must be actual observations from the sample journey;
fixture observations cannot establish connected acceptance.

For purchase handoff, handoffs is an ordered list of named custody, inspection
or quality steps in that journey object. Each step must use its producer's actual
command, including signed physical receipt or entered inspection observations.
Dispatch never substitutes for receipt. Custody action determines the expected
producer state; quality requires satisfactory and inspection requires passed.
The release check requires the actual unheld buyer receipt and the current
release preview. The runner never advances the clock or invents elapsed time.
The original release operation is resolved before another transfer is attempted.

The published allocation and service-assessment boundaries are not mounted by
this folder. Their owning composition must declare command and lookup transport
patterns under composition.allocation and composition.service_assessment in the
journey input. Patterns are relative /internal/ gateway routes, with {subject}
and {operation} substitutions. They must expose the published typed job
allocation and actual service-assessment producers. Missing composition returns
a named current_transport failure. No untyped legacy job allocation is used.

## Negative and recovery execution

Each journey has cases entries for denied, stale, cross_account, cross_business,
timeout, lost_response, duplicate, restart and recovery. Each entry has the same
command fields as a producer step, plus guard naming an acknowledged producer
step. Cross-account also names other_actor. Commands use separate retained
references so replay of an earlier successful command cannot certify first
response loss. The acknowledged guard is read before execution and checked again
after restoration. Changed-source rejection must carry a stale/source code;
an unrelated conflict cannot pass. Timeout must return responsible pending
metadata within five seconds and recover the same reference after restoration.
Both timeout and recovery require a pending reason, responsible owner, next action
and review time before proceeding.
Recovery begins with an actual pending operation. Lost response discards the
first delivery reply, reads the operation and replays its identical binding.

Native lifecycle controls use RUN/e06-control.sock, a private local stream
socket supplied by the stack owner. Requests are bounded newline-delimited JSON:
schema_version 1, journey, case, phase, operation_id. The exact request plus
acknowledged true is the acknowledgement. Missing controls fail by name; they
never become a skipped or passed case. Phases arm and restore bracket permission
revocation, authoritative source change, selected membership change, dependency
timeout and restart. Restart requires the first delivery to end in a transport interruption;
a complete mutation response fails that case. Its restart acknowledgement must
add interruption with operation_id matching the retained command, acknowledged
true and response_delivered false, confirming interruption after the owning
runtime acknowledged the command and before its response was delivered. Only then
does the runner reconcile and replay the same command; recovery invokes resolve before reconciliation. Controls must change
the actual owning runtime, never return a substitute producer result. Cleanup
runs even when an assertion fails.

Duplicate delivery invokes signed_callback. Its acknowledgement additionally
contains callback with raw (the exact simulator JSON bytes as a string) and
signature. The runner checks its order, actor, attempt, quote revision, currency,
amount and outcome against current checkout, then sends the identical bytes and
signature twice to the real signed receiver through the gateway. It checks one
retained attempt and unchanged commercial facts. Callback bytes and signatures
never enter the summary. A capture from a fixture cannot certify delivery.

The current shared composition still owes several mounted adapters and lifecycle
controls. Missing inputs, producer transport, authority, observations or controls
remain named failed scenarios. Reaching a context or receiving a control
acknowledgement does not certify a complete journey. Connected proof remains
owed until the command completes against the running stack with actual inputs.

Focused checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/integration/sprint-2 -p 'test_*.py'
```
