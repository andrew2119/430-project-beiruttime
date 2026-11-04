# Private seller application API v1

All requests use a current Buyer Bearer session; account status and lineage are rechecked inside Identity. The caller never supplies another applicant id or a role grant.

## Read and submit

- `GET /v1/private-seller/applications/me` → `{application: PrivateApplication | null}` for this account only.
- `POST /v1/private-seller/applications` requires `Idempotency-Key` (8–100 characters) and JSON:

```json
{"identity_name":"DEMO synthetic person","contact":"sample@example.test","payout_reference":"DEMO-RECIPIENT","identity_evidence":"DEMO: synthetic identity","possession_evidence":"DEMO: synthetic possession","expected_revision":0}
```

Identity/contact are bounded meaningful text. Payout references match `DEMO-[A-Za-z0-9-]{4,64}`. Each proof starts `DEMO:` and is at most 65,536 UTF-8 bytes; real identity/payout documents are not accepted for this course demonstration. Browser file inputs read synthetic text and send these bytes as JSON; filenames are not persisted.

The initial revision is 1/status pending. Existing correction/rejected cases require their exact current revision and become pending at the next revision. Pending, approved and suspended cases cannot be overwritten by the applicant. A duplicate operation returns its original outcome; changed payload/key reuse or stale revisions return 409 without new bytes/events.

Response `{application: PrivateApplication}` includes id, subject_id, revision, status, identity_name, contact, payout_reference, reason, created_at and updated_at, never evidence bytes or public proof links. The TypeScript DTO is in `index.ts`. Saved case identity/revision remains authoritative across restarts and language changes.

## Private bytes and review boundary

`GET /v1/private-seller/applications/{application_id}/evidence/{evidence_id}` returns an attachment only to the applicant or a currently assigned reviewer with the individual/platform permission `identity.private-seller.review`. Roles alone grant no read access. Guessed cross-case/cross-user requests are denied and audited without byte logging. Case/applicant binding is also protected by a compound foreign key.

L02 owns assignment, reasoned verdict/history, correction and revocation. Use the account-lock and grant/session-fence protocol in `INTERNAL.md`. Application approval and the private_seller / identity.listings.publish capability must change atomically; self-review is forbidden. No application can create a dealer/brand grant or a physical watch-authentication result.

Submission writes case, bounded evidence, receipt, audit and the identifiers-only `identity.private-seller-submitted.v1` outbox intent in one transaction. An outbox failure rolls everything back. The opt-in Accounts demo fixture creates only a labeled sample buyer and a pending application through these operations; it never approves a case.
