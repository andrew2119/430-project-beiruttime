# Finish consent v1

`v1.py` is the closed command/source schema; `index.ts` is its consumer shape.
All examples are synthetic and establish no custody, payment or execution proof.

- `POST /v1/finish/consents` takes Command. The authenticated buyer must equal actor_id.
- `GET /v1/finish/subjects/{subject}/operations/{operation}` resolves a lost response under fresh authority. Unknown references return 404, never presumed failure or success.
- The pending result preserves the entire stable operation reference. Retry exactly the same command. Reusing its reference with different bytes returns conflict.
- The detail adapter supplies `{source,revision,choices}` for `GET /v1/finish/subjects/{subject}` from the current source plus the durable consent. It must authorize before exposing either record.

Every area must have exactly one explicit choice. No default is consent. Unknown original finish, coating, plating, engraving or unsuitability forbids intervention. The customer may instead record no-polish; an alternative requires a fresh assessment and quote. Changing areas, desired finish, limits or any source fact increments source_revision and requires renewed review. A recorded consent never grants work execution, custody, payment or release permission.

Current-source acquisition must authenticate the current buyer, selected business, assignment, watch commitment, retained quote and policy. Its serialized revision fence lasts through receipt commit. The two-second acquisition budget includes reads. `valid_until` is an authority lease, not an expiry on retained economics. Server UTC time strictly before the boundary permits consent; equality and after are stale. Revoked access blocks even duplicate recovery. Private source and command records are never public events or logs.

The additive SQL and connection adapter provide a local durable receipt/outbox implementation with an immutable private source snapshot per operation. Each request requires its own connection; never share a connection across request threads. Storage lock acquisition is bounded to 250 milliseconds and authority is rechecked before commit. Request bodies are limited to 32 KiB with a two-second read budget. The outbox contains references only and uses operation_id as publication deduplication key. Production database adaptation, inbox publication acknowledgement and runtime composition are deferred; no module registration is added. No provider is inferred from a cache. A real source adapter must satisfy the fence contract before connected acceptance, and rerun denied, stale, timeout, duplicate and restart proofs.

Fixtures: source and command are deterministic inputs, success is the expected receipt, denied and stale are source variants, and lost-response is an uncertain result requiring lookup or same-reference retry.

The required `terms` snapshot retains complete English and Arabic fee, return and assurance text, its revision and the support inbox destination. A changed term or terms revision must increment source_revision and quote_revision before renewed consent. Receipt snapshots preserve the original terms. The detail contract rejects missing terms; the form displays all three terms and support access before opening confirmation.
