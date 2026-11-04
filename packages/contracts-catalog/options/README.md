# Catalog brand options V1

`catalog.brand-options.v1` describes saved buyer intent, never a feasibility, authenticity, production or payment approval. Color, material, dial and sophistication are supplied by L10; movement remains L11's distinct module.

## HTTP contract

All paths have prefix `/v1/brand-options`. Browser callers use the registered same-origin `/api/web/v1/catalog` or `/api/mobile/v1/catalog` gateway. Private calls require a current Identity Bearer token. Neither caller-supplied actor headers nor organization IDs grant authority.

- `GET /brands`: public, currently onboarded official brands offering customization.
- `GET /brands/{organization_id}`: public brand catalog, including unavailable latest options so the UI never invents availability. Maximum 200 options per brand.
- `PUT /brands/{organization_id}/{kind}/{option_id}`: create or append an immutable revision. Requires the released `business.jobs.write` capability in the verified actor's selected organization grant and a current directory brand. Body is `OptionWrite`; `expected_revision=0` creates revision 1. An unavailable update is a new revision, not a mutation of prior saved definitions.
- `GET /configurations`: latest 50 configurations belonging only to the current subject.
- `GET /configurations/{id}`: canonical private snapshot, including exact option revisions, base model, caliber and private reference IDs. Top-level `reference_ids` is the owner's uploaded inventory (including not-yet-attached images); only `selections[].reference_ids` binds an image to a chosen dial. Optional `expected_revision=N` rejects a changed configuration with `stale_configuration` (409).
- `PUT /configurations/{id}/{kind}`: save `SelectionWrite`. The first selection creates the configuration; later selections require its exact aggregate revision. The brand, base and caliber cannot change in an existing configuration. The current option must be available and support that exact component/base/caliber. Kind is one of `color`, `material`, `dial`, `sophistication`.
- `POST /configurations/{id}/references`: binary `image/png`, at most 1 MiB, three files per configuration. Requires an already-owned configuration. The narrow decoder accepts non-interlaced 8-bit grayscale/RGB/RGBA PNG, at most 2048 per side and 1,048,576 total pixels, with verified CRCs and bounded inflated data. Metadata, SVG, animation, unknown chunks, URLs and trailing content are rejected. Reference IDs may be attached only to a dial selection on the same owner's same configuration.
- `GET /configurations/{id}/references/{reference_id}`: authorized bytes only, `no-store`; foreign or unknown references return the same 404. No public file URL exists.

All writes require an 8–100 character `[A-Za-z0-9_-]` `Idempotency-Key`. Replays return the stored original result; reusing a key for different content returns 409. Keys are scoped by subject across all commands. Commands serialize operation keys and configuration/catalog writes in a connection-bound PostgreSQL transaction. Acknowledged configuration and image content survive a process restart.

Useful stable errors: `stale_option`, `stale_configuration`, `unsupported_option`, `configuration_binding`, `brand_unavailable`, `unsafe_reference`, `reference_limit`, `idempotency_conflict`, `dependency_unavailable`. Validation errors never echo rejected values.

## Consumers

A private request may bind the returned configuration `id`, `revision` and complete `selections` snapshot. Read with `expected_revision` before capturing it. L08's provisional `/v1/brands/{brand_id}/options` URL is not this released contract: catalog reads use `/v1/brand-options/brands/{brand_id}`. A neutral draft's bare option IDs must not replace exact selection revision/component bindings. Never share the top-level uploaded inventory as if every image had been attached to the request. Keep `option_revision` and component/base/caliber together. Do not reinterpret the `not_assessed` feasibility or `saved_not_submitted` state as a quote, submission or approval. Changed options remain visible as immutable saved intent with `current=false`; a new source choice must be explicitly saved before treating it as current.

The next-step link is contributed only when `/custom-requests` exists in the route registry. It carries `configuration` and `revision` query parameters, not private file bytes.

## Upstream integration

Identity uses foundation `GET /internal/v1/principal` and `CurrentPrincipal`. Publication passes `organization_id` to Identity to select a currently held membership, then requires its matching organization grant; a URL organization ID cannot create authority. Every brand catalog/discovery/selection also intersects the directory with Identity's released `GET /v1/businesses` / OfficialBusiness V1 authority: active brand, customization capability, platform onboarding and authenticated-business flags must all be current. A stale directory cannot revive a revoked business, and either producer's sample marker is preserved. Durable private snapshots still reopen during upstream failure. Each dependency owns its timeout (1.5s), connection/concurrency budget and circuit breaker. An outage is an explicit 503; it never creates a local success.

The provisional directory fixture expects `GET /v1/directory?kind=brand&offering=customization` with `{items:[{organization_id,name:{en,ar},kind,status,offerings,sample}]}`. Only `kind=brand,status=onboarded` with customization is admitted. This strict transport fixture is for parallel development; the adapter must be reconciled to L11's provider contract before connected acceptance. It does not install production fixture routes.

The frontend consumes Identity's `useSession` and `authenticatedRequest` directly. Binary image reads use the same live memory credential and one coordinated Identity refresh; tokens never enter URLs, query keys or persistence. Identity's released gateway registration and actual runtime must be present before authenticated browser acceptance; a credential field, stored token or simulated sign-in is not an alternative.

## Durable events

Successful commands atomically append authenticated-delivery intent to foundation outbox under destination `communications`:

- `catalog.brand-option-published.v1`
- `catalog.brand-selection-saved.v1`
- `catalog.brand-reference-saved.v1`

Envelopes contain only resource ID, revision, request reference and authoritative UTC time. No option text, file reference IDs, bytes or private buyer evidence is published. The bounded relay uses `BT_OPTIONS_EVENT_TOKEN`; without that service credential intent remains pending, never falsely acknowledged. Communications must allow these event types before delivery is enabled.

## Sample content

`fixtures/options.v1.json` labels every definition as sample content. The opt-in `L10.options-color demo` fixture requires an already-onboarded sample brand, a current authorized brand token (`BT_OPTIONS_SAMPLE_BRAND`, `BT_OPTIONS_BRAND_TOKEN`) and calls real publication operations. It never writes seed rows directly or creates a buyer selection, feasibility pass or paid order. The USD price reference is integer minor units (cents); LBP uses integer whole pounds. It is a reference, not a current quote.
