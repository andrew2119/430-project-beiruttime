# Service directory and movement V1

Directory owner: Service Operations. Movement owner: Catalog.

- `GET /v1/directory/businesses?purpose=servicing|customization&limit=20&after=<uuid>` returns published profiles revalidated against current Identity onboarding. Only active official brands/dealers are public; customization requires an active brand and the customization capability. Dependency failure returns 503, never cached eligibility.
- `GET /v1/directory/businesses/{organization_id}` returns the same public projection.
- `GET /v1/directory/providers/{organization_id}` is the Intake V1 eligibility projection: `{organization_id,official:true,active:true,kind:"brand"|"dealer"}` only after the same published-profile and fresh Identity checks. Inactive/unpublished businesses return no proof; these markers concern business onboarding, never watch inspection or work completion.
- `PUT /v1/directory/businesses/{organization_id}` requires current selected organization and `business.jobs.write`, `expected_revision` (0 creates), and `Idempotency-Key`. The service checks current Identity onboarding before publication.
- `POST /v1/directory/choices` persists the current buyer's destination/capability selection; this is not an appointment, accepted service job, custody receipt or work pass.
- `GET /v1/directory/choices/current` reads that buyer's saved choice only.
- `GET /v1/options/movement?brand_id=<uuid>&limit=20&after=<uuid>` returns current brand-supported movements with a bounded cursor. `GET /v1/options/movement/{id}` restores a specific currently published option even when it lies beyond the first page.
- `PUT /v1/options/movement/{id}` requires the selected brand's `business.stock.write` grant; stores identified caliber, case/dial/hand/function compatibility and indicative quote impact in integer minor units.
- `POST /v1/options/movement/selections` requires a signed-in buyer, expected selection and option revisions, and `Idempotency-Key`; saves an owner-private selection with `supported_for_review` or `manual_review`, never a physical feasibility pass.
- `GET /v1/options/movement/selections/current?brand_id=<uuid>` restores only the current actor's selection. Saved selection/units survive locale and reload.

Identity Businesses V1: `GET /internal/v1/principal?organization_id=<uuid>` selects a current held organization using the frozen CurrentPrincipal contract. `GET /v1/businesses/{organization_id}` returns `{id,public_name,kind,capabilities,state,revision,sample,platform_onboarded,authenticated_business,independent_watch_authentication_required:false}`. The adapter requires an exact ID, active state, true onboarding/authenticated-business flags and the currently declared coarse `servicing` or brand-only `customization` capability. Fine-grained directory claims can never enlarge those onboarding capabilities. Service profile publication uses `business.jobs.write`; brand movement publication uses `business.stock.write`, both in the selected organization's current grant. Consumer fixture tests implement this published V1 seam; connected-service proof is recorded separately.

All writes use PostgreSQL transactions and outbox intent. Request replay is scoped to actor, command and key; different content with an existing key is a conflict. Revision checks run under the same transaction lock. Demo fixtures are explicit authorized API imports, never boot-time seeds.

## Durable event intent

Versioned events are `service.directory-published.v1`, `service.directory-choice-saved.v1`, `catalog.movement-published.v1` and `catalog.movement-selected.v1`. Each uses contracts-core EventEnvelope V1 with exact data `{resource_id,revision}` and its owning service as source. No scope text, contact, configuration, quote amount or private buyer evidence is emitted. The relay signs a 60-second RS256 token with configured Identity issuer, `type:service`, `sub:service-operations|catalog` and `aud:communications`.

The final generic Communications receiver contract is still an integration prerequisite: the published `/internal/v1/events` bid-notices receiver is Auction-only, not acknowledgement for these types. Missing or refusing receivers leave durable pending intent; the screen does not claim a notification was delivered. A signed transport-fixture acknowledgement proves relay mechanics only, never real Communications acceptance. No service appointment, work request or feasibility pass is manufactured from a selection event.
