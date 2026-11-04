# Validation record — 4 November 2026

## Passed

- Identity Docker suite after merging main: **37 passed** against isolated PostgreSQL databases/restricted roles. This includes account/session lifecycle, concurrent duplicate commands, expired/one-use recovery, purpose/session/recipient-bound reauthentication, current assigned-reviewer access, scoped organization permissions, stable fingerprints, outbox rollback and cancelled-KDF capacity retention.
- Eligibility Docker suite after merging main: **28 passed**. The owning API uses the published owner-private request-drafts.v1 read and businesses.v1 assurance read. Fixtures enforce owner scope, brand availability/revocation and the exact response contracts; none is a production fallback. Consent refusal stores no evidence, unavailable dependencies create no records, and withdrawal fences/deduplication are verified.
- Web foundation tests after merging main: **66 passed**; Identity browser-client/SSR form tests: **14 passed**. All private forms use native POST fallback so pre-hydration submission cannot put credentials/evidence references in GET URLs. TypeScript, ESLint and production build pass.
- Real Docker COPY-context and Git-ignore smoke passes. Both owned proof images were checked for absence of local environment/signing files. Earlier synthetic proof material was rotated and only owned proof images/containers were removed; shared storage/build cache were untouched.

## Real browser and connected-service evidence

English desktop registration and Arabic phone registration both reached the actual Identity service. The Arabic flow returned to the intended private-selling page. Both submitted synthetic evidence through the real form/API and obtained persisted pending private cases, not approval or physical-inspection claims. The Arabic phone case retained the same reference across language/theme navigation. Acknowledged records survived web/runtime replacement.

Authenticated account, seller and consent screens passed all EN/AR × light/dark combinations at actual viewports **1440×900**, **390×844**, **320×700** and **932×430** (48 screen cases). Checks assert viewport dimensions, direction/theme, absence of clipping/horizontal overflow, 44px targets and 16px input fonts. The principal desktop/390px matrix was repeated after the foundation locale/proxy changes. Synthetic evidence remained absent from public text and browser storage. Sign-out removed the access context and private draft conveniences. Native form submission was exercised without React's submit handler and did not put credentials in the URL or claim sign-in. A real password change retained its acknowledged success when subsequent cookie cleanup failed in an injected browser-transport check; the synthetic password was then restored through the real service.

A standalone production web Docker image published on a different host/container port used the configured-public-origin gateway against real Identity/Eligibility. Login, cookie refresh rotation, owner-private case access and logout passed. Revoked access/refresh returned 401; foreign/missing Origin returned 403. A real Chromium sign-out/sign-in through the Docker-published port also passed. The temporary proof container/image were removed afterward.

Browser evidence is functional/DOM geometry, not a physical-device or pixel-diff certificate. Physical phone keyboard, installation, screen-reader and minimum-browser acceptance remain separate.

The opt-in sample fixture was also invoked against the running service using an existing image and read-only source. It registered/signed in a labeled synthetic buyer, created a genuine pending private case, and confirmed sign-out. No privilege grant or review pass was seeded. Full fixture tests reused the existing proof image; no new image was built.

## Remaining connected demo gate

The positive consent demonstration still requires a real owner-private customization draft and an active official customization brand from the L08/L02 modules. Their versioned contracts are consumed and tested, but those routes were not yet integrated into the shared running services at this validation checkpoint. No substitute request, business assurance, review pass, payment or production outcome was fabricated. Until real providers are available, the UI correctly denies unavailable/unknown references; withdrawal acknowledgement remains pending when owning consumers have not fenced.

The foundation was integrated with a normal merge from main. All 189 foundation files were verified byte-identical to main after replacing older copied snapshots with the authoritative versions. The Docker suites reused existing test images with current read-only source mounts; no new images were built. Web tests, TypeScript, ESLint, production build and all 48 authenticated browser screen cases were repeated successfully after integration. Only lane-owned changes differ from main.
