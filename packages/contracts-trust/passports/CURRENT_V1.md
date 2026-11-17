# Inspection summaries v1

Issue: `POST /internal/v1/passports`; operation lookup:
`GET /internal/v1/passports/operations/{operation_id}`. Both require current
identity, organization, record permission and source scope, including on retry.
Public QR destination: `/passports/{passport_id}`; public verification:
`GET /public/v1/passports/{passport_id}`. Public routes accept no field expansion.
A supplied signed document can be checked with `POST /public/v1/passports/verify`.
Request limit is 4096 bytes; unknown fields and malformed identifiers are rejected.

`v1.py` is the closed wire schema. UUIDs and UTC dates serialize as strings.
The signature is Ed25519 over UTF-8 sorted-key compact JSON of the summary,
with ASCII escaping, prefixed by `beirut-time.passports.summary.v1\n`.
Keys and issuer identities are pinned by the service, never supplied by readers.
Old verification keys must remain available; signing keys stay outside records.

Issuance consumes a fresh authoritative snapshot bound to actor, subject,
organization, watch, inspection, revision, assignment, custody receipt, commitment,
retained quote and policy revisions. It requires a paid, physically received,
independently inspected private sale with a pass and released completion.
The expert differs from the seller. Source permission is checked before replay
or lookup. A projection cannot authorize issuance. Source reads have a bounded
timeout and must provide a serialized source guard through local receipt commit;
without that capability composition remains unavailable. This module owns no
custody, allocation or financial authority.

The stable operation receipt stores the exact request, actor, source bindings,
signed result and revision. Same request replays; conflicting use is 409.
Stale source is 409; denied access is 403; absent/passless inspection is 409;
unknown or timed-out authority is 503 with the same operation reference for retry.
No success is returned until commit. Operation lookup missing is 404, never
proof an uncertain write failed. A unique inspection prevents duplicate issuance.
Receipts and outbox rows commit atomically; publication uses the receipt ID as
its deduplication key. No private evidence appears in the public event.

Only the closed signed summary is public. Serial, private owners, inspection IDs,
evidence, custody, economics and internal source bindings are never public.
The random watch reference is unrelated to the serial or private watch ID.
Verification proves the issuer signed this historical summary, not the physical
object, current condition, current ownership or factory endorsement. Later work
never edits the old summary. Resale history and owner evidence are not exposed.
