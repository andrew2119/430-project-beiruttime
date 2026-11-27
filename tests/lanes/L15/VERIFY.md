# Listing revision and brand requests

## Implemented boundaries

- Published edits retain an intent before HTTP and capture the Orders revision once. New operations use Auction v3 prepare/dispatch, Orders commitment, atomic Catalog facts/history/outbox, Orders completion, then Auction commit. Existing retained v2 operations keep their protocol and identity. Unknown outcomes stay pending. An Orders denial clears the source only after independently confirmed exact Auction abort. No SQL transaction spans HTTP. Current owner/org/publication permission and source revision are rechecked; sale-method conversion is not a facts edit. Only a committed price difference emits a price-change event.
- Configuration validation reads all five existing dimensions under their Catalog source locks. Exact option revisions, brand/base/caliber, availability, movement mounting and brand-authored combination rules are checked separately from physical feasibility. A rule binds all five IDs/revisions and mounting; no rule means manual assessment. Exact same-author rule PUT replay returns its immutable acknowledgment without another version/event. Option prices remain indicative.
- Submission locks the owned saved draft, revalidates its all-five digest, retains notes and only explicitly attached references, and creates one immutable request. Submitted sources cannot mutate, even while optional readiness is unavailable. Corrections append history and require fresh human permission plus Service Operations authentication and its independently fenced current assignment. Minimal service reads exclude notes/images.
- Brand decisions retain intent before prerequisite/approval HTTP. Current feasible qualified assessment, buyer-accepted exact quote and independent serialized grant must match. Lost consume replies retain bindings and operation identity for reconciliation. Authorization is checked again before confirmation. Approval is explicitly not execution authority. Optional readiness reports a discriminated unavailable result without fabricated bindings; decision commands independently fail closed.

## Module and interface design

New modules include nested `listings/revisions` and `request-drafts/submission`. Legacy IDs and applied migrations are unchanged. Full Catalog migrations run together, without foreign keys to later-loading modules. Runtime-local listing helpers preserve existing imports and expose the source lock/pending-edit guard for withdrawal.

Browser commands have additive v1 gateway aliases; canonical service contracts remain versioned. Technical corrections are not browser capabilities. Copied provider/foundation files are excluded from this lane's commits. Local proof profiles and credentials are excluded from Git and Catalog Docker contexts.

## Completed checks

The guarded final validation rebuilt only the Catalog runtime image and reused the existing test image with read-only current source:

- L15 Catalog: **91 passed**, three intentional core-only skips, one upstream deprecation warning.
- Existing Catalog suites: L03 77 passed; L04 40; L08 37; L10 100; L11 37. Each invocation repeats common proofs; these are not unique-test totals.
- Full web suites, typecheck, lint and production build passed. Focused coverage includes seven brand decision view tests, sixteen listing editor tests and three submitted-source memory tests.
- Python lint, syntax and whitespace checks passed.
- Automated final visual proof completed **32 actual viewport checks** and **32 headless captures**, covering configuration, private requests, brand decisions and the published listing editor in EN/AR, light/dark, 1280px desktop and asserted **390px inner width**. Visible-element bounds and RTL were checked; the hidden shared tab measurement ruler is intentionally excluded.

## Connected behavior demonstrated

All sample content is explicitly labelled. Identity, Catalog, Directory, Pricing, Orders and Auction were exercised through their real APIs in isolated restricted databases, starting only the domains needed by each check. No payment, job, physical receipt or technical pass was seeded.

- A buyer signed in through the real form, explicitly attached a private synthetic PNG to a dial snapshot, reviewed all five dimensions and submitted one immutable request. Its initial `manual_assessment` was not presented as physical feasibility. Reopening retained the same request/revision.
- The selected brand loaded the actual private PNG. Another brand workspace was denied and displayed zero private images.
- The brand published a real exact-scope compatibility rule. Buyer revalidation showed support for review without altering the previously submitted snapshot. Discarding a successful PUT body and replaying the exact command added only one rule version.
- A real fixed-price edit initially exposed a canonical Auction no-lot finalize defect. With published kernel v3.0.1, browser reconciliation recovered the **same** retained operation, producing listing revision 4, one history entry and one price-event intent.
- A buyer then obtained/reviewed a real purchase quote and reserved that watch through Orders. A subsequent owner price edit was denied before Auction prepare; listing revision/price, history count and price-event count remained unchanged. The browser explained the publication/commitment guard rather than claiming a saved draft or successful revision.
- Directory unavailability did not unlock the submitted source. Missing approval prerequisites kept approval disabled even after a valid reason was entered; unavailable readiness did not masquerade as available bindings.
- Client navigation retains source configuration through reactive search parameters and a keyed workspace. Recovery reads follow movement loading to respect the existing BFF concurrency budget.

Own browser, web process and proof services were stopped after every completed run. Loopback proof ports were verified closed; shared PostgreSQL was not stopped. Ignored `.artifacts/` contains local logs, matrix records and screenshots, plus synthetic credentials that must never be committed. Native headless captures use requested window dimensions; actual device-emulated DOM geometry establishes the 390px claim.

## Remaining connected acceptance

These are not inferred from fixture success:

1. A live post-dispatch Orders denial followed by independently confirmed Auction abort/reconciliation. The live reserved-watch case proves pre-prepare denial; retained post-prepare/abort cases are covered by regression fixtures.
2. Published Brand Assessment and Eligibility grant wire contracts, followed by a real current feasible-assessment/accepted-quote/independent-grant positive decision. Pricing already follows `pricing-current/v2`; the two missing provider adapters remain explicitly provisional and unavailable, never local-success fallbacks.
3. Downstream delivery after receiver subscriptions are published. New outbox destinations remain inactive until then; no all-outboxes-drained claim is made.
