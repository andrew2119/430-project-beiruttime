# Identity businesses, contacts and private review V1

L02 extends the one Identity runtime. It owns no independent Identity service or database. Domain state, capability changes, audit history, idempotent receipts and outbox intent share one PostgreSQL transaction.

## Consumer authority

`GET /internal/v1/principal` is the current Accounts authority: RS256 user token, active account and unrevoked session lineage. Set its `organization_id` query parameter to select a held business. Organization permissions never enter top-level platform permissions. No caller actor, role or organization header is trusted.

Operator permissions are exact:

- `identity.businesses.manage`: official onboarding, revocation and reactivation.
- `identity.membership.manage`: scoped staff capability grants and changes.
- `identity.private-seller.assign`: independent reviewer assignment/reassignment.
- `identity.private-seller.review`: only the currently assigned reviewer may inspect evidence or decide; the applicant cannot review themselves.

Staff capabilities are `business.stock.write`, `business.jobs.write`, `business.records.read`, `business.staff.manage`. Stock-write grants also include the canonical `identity.listings.publish` permission **inside the same organization grant**. A staff command must require the selected organization, current active business/membership, and its exact capability. A role in a different business grants nothing.

Membership changes and business revocation update `identity_access_grants`, bump access revision and revoke affected session lineages atomically under UUID-ordered account row locks. Refresh and resumed commands cannot escape this fence. Reactivation restores only current active memberships, never revoked colleagues.

## Official business read API

- `GET /v1/businesses`: at most 100 current active official businesses.
- `GET /v1/businesses/:id`: current public status, including revoked assurance.
- `GET /v1/businesses/manage/records`: operator-only current and revoked records.

`OfficialBusiness` in TypeScript/Python is the public V1 DTO. Legal identity, assurance reference, staff identifiers and contact details never appear in it. Active official dealer/brand records are platform-onboarded and authenticated businesses by default; this does not fabricate an independent physical watch inspection. All sample records carry `sample: true`.

`POST /v1/businesses` requires an operator, legal/public names, dealer/brand kind, supported capabilities, private assurance reference and reason. Dealers cannot claim brand customization. `PATCH /v1/businesses/:id` requires the current revision, active/revoked state and reason. There is no public business application API.

## Membership API

`POST /v1/memberships`; `GET /v1/businesses/:id/memberships`; `PATCH /v1/memberships/:id`.

Grants bind an existing active colleague to one active official business, exact capabilities, qualifications and intervention scope. Updates require revision and reason, preserve complete capability snapshots and support active/suspended/revoked states. A human cannot issue or intervene in their own privileged membership.

## Verified delivery contacts

`GET /v1/contacts` is owner-private. It returns only that person's current verified recipients and resumable pending-challenge metadata. Proposed recipients never replace the current delivery contact until code proof succeeds.

1. Use the Accounts browser `authenticatedRequest` to `POST /v1/accounts/reauthenticate` with `{password,purpose:"contact-change",binding:"email:<normalized email>"}` (or `phone:<canonical phone>`).
2. `POST /v1/contacts/challenges` with `{channel,recipient,revision,proof}` plus an `Idempotency-Key`. Proof is subject/session/purpose/recipient-bound, expires in five minutes and is consumed inside the same transaction, after an existing-operation lookup. It never enters the receipt, events or logs.
3. `POST /v1/contacts/challenges/:id/verify` with a six-digit code. Codes expire at ten minutes (equality is expired), stop after five wrong attempts and are single-use. Challenges are limited to once/minute and five/hour. Arabic phone/code digits normalize without changing an email mailbox's local part.

`GET /internal/v1/contacts/:subject/delivery` is **not a public gateway route**. Only an RS256 service token with subject `communications`, type `service`, Identity audience and the configured issuer may read it. It returns verified email/phone or null; a pending address can never enter this projection.

Normal delivery writes authenticated private outbox intent and honestly reports `delivery_pending`. `BT_CONTACT_SIMULATOR=1` enables an explicitly labeled owner-only sample code reader; it is off by default. The simulator never verifies a contact by itself. Accepted simulated contacts retain `email_sample` / `phone_sample` in their owner and private delivery DTOs, and remain explicitly labeled sample verification in the UI, including after restart or schema upgrade. Proofs, codes and recipients are not persisted in browser storage.

## Private seller review

`GET/POST /v1/private-reviews`; `GET /v1/private-reviews/:id`; `POST /v1/private-reviews/:id/verdict`; `POST /v1/private-reviews/:id/reassign`; owner-private `GET /v1/private-reviews/mine`.

Private applications and evidence are owned by the private-seller module. The authorized same-domain review seam locks all affected accounts in UUID order, rechecks current permission/assignment, compares application and review revisions and changes the application plus individual `private_seller` / `identity.listings.publish` grant atomically. Rejection/suspension revoke that grant and session lineages. A private approval cannot create dealer/brand authority or a physical watch authentication pass.

Assigned reviewers can list `GET /v1/private-reviews/:id/evidence` and download `GET /v1/private-reviews/:id/files/:file`. The scoped-file adapter binds bytes to the private case/applicant and current independent reviewer, caps reads at 2 MiB, serves attachments with no-store/nosniff and durably audits both allowed and denied reads. Reassignment revokes the old private-seller assignment in the same transaction. Applicants can see reasoned history, not another applicant's proof. History reads return at most 100 decisions, with `history_before_revision` for earlier pages; the reviewer and applicant screens can load those earlier pages without discarding acknowledged history.

## Idempotency, events and samples

Create, verdict, reassignment and revisioned mutations require bounded operation keys. Changed payloads conflict; an uncertain retry preserves its original outcome. Private contact proof consumption rolls back if the rest of the command fails. Outbox failure rolls back domain state, receipt and history.

Versioned event types: `identity.business-onboarded.v1`, `identity.business-status-changed.v1`, `identity.membership-changed.v1`, `identity.contact-challenge.v1`, `identity.contact-verified.v1`, `identity.private-review-assigned.v1`, `identity.private-seller-reviewed.v1`. Only private challenge-delivery events contain a recipient/code, addressed exclusively to Communications. All other events contain opaque identifiers, status/revision and sample markers, never private evidence or reasons. Missing receivers leave durable delivery pending.

The opt-in `L02.businesses demo` fixture requires an authorized operator and an existing sample colleague, then calls real onboarding/membership APIs for a labeled sample dealer and brand. It never seeds a paid order, winning bid, independent inspection, receipt or payout.
