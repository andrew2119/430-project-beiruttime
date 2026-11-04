# L10 verification

Run `./tests/lanes/L10/verify.sh` from an isolated checkout. It builds a per-run non-root test image, exercises real PostgreSQL transactions and restricted credentials, runs Python static checks, builds Next.js and runs both foundation and feature web tests. Shared PostgreSQL is preserved. Every proof creates and drops its own database and roles; ordinary domain databases are never migrated by this suite.

`BT_MODULES_PATH=/tmp/l10-core-baseline` keeps generic migration proofs on their core-only starting schema. L10 tests explicitly migrate `/app/modules` into their own disposable database before invoking real owning-service routes. This avoids comparing the generic temporary migration fixture against an already-installed domain migration ledger.

Coverage includes all four stories, exact revision boundaries/types, owner and selected-organization scope, unavailable dependencies, unsupported/foreign options, unavailable material and stale snapshots, duplicate/concurrent operations, restart recovery, safe and unsafe PNGs, private file access and cross-configuration attachment, integer price references, and transactional outbox intent. Sample publication runs twice through authorized APIs to prove replay safety without creating a buyer configuration.

## Parallel-development browser proof

`tests/lanes/L10/compose.yaml` is intentionally **not** included in root composition. It starts only a disposable Catalog proof server on `127.0.0.1:9110`. The server uses real migrations, PostgreSQL and owning-service operations. Identity and directory transports are explicitly deterministic fixtures; it is not connected marketplace acceptance and must not be used as a production runtime.

Build its parent image first:

```sh
docker build --target test -f services/_template/runtime/Dockerfile -t beirut-time/l10-foundation:test .
docker compose -f tests/lanes/L10/compose.yaml up -d --build
BT_PUBLIC_WEB_ORIGINS=http://localhost:3110,http://127.0.0.1:3110 BT_TRUST_FORWARDED_ORIGIN=false CATALOG_API_URL=http://127.0.0.1:9110 web/node_modules/.bin/next start web --port 3110
```

Open `/en/customize?brand=20000000-0000-4000-8000-000000000001&base=atelier-38&caliber=manual-01` and its `/ar/` equivalent. Use the real locale/theme controls. Emulate `390x844x3,mobile,touch` and assert `window.innerWidth === 390` rather than resizing desktop Chrome alone, which may clamp to 500px. Check all category controls and keyboard radio selection, sample labels, precise material/provenance/package details, 44px inputs, 16px phone editable text, no horizontal overflow, honest signed-out saving and dependency failure recovery.

If native `--window-size=390,...` screenshots crop the RTL page on this Mac, use an isolated headless Chrome with a local debug port, set its exact viewport through the browser CLI, then run `node tests/lanes/L10/capture-native.mjs <port> <output.png>`. This utility reads pixels only; navigation, theme controls and viewport assertions stay in the browser proof. Whole-viewport capture avoids manual clip offsets in emulated RTL.

Stop only this proof with `docker compose -f tests/lanes/L10/compose.yaml down`. Graceful shutdown drops the proof database. Do not stop the shared PostgreSQL instance.

## Provisional results (2026-11-04)

- Docker/PostgreSQL suite: 80 passed, no skips; one upstream Starlette deprecation warning. Includes the refreshed foundation destination-isolation proof.
- Web with the released Identity SDK: production build and type check passed; 58 foundation plus 19 feature tests passed.
- Python static checks, contract discovery and Compose validation passed.
- Refreshed real Chrome public-flow matrix with the published Identity SDK and foundation proxy/origin patches: 32 checks (four categories × two languages × two themes × 1440px/390px), including exact phone emulation, native radio selection, no horizontal overflow, 44px controls, 16px phone input text, sample labels and disabled signed-out saving.
- Production GET/HEAD on both loopback hostnames returns 200 without redirects in both languages. Nested environment exclusion proof passed.
- Native pixel captures were visually reviewed in desktop English and phone Arabic, both themes. The browser Catalog uses real disposable PostgreSQL; its upstream Identity and directory transports are explicit fixtures, and the not-yet-contributed Identity gateway honestly shows saved choices unavailable. These results do not close connected authenticated acceptance.

## Connected acceptance gate

After foundation and the owning lanes land, take the owning L01 SDK and gateway registration from main, reconcile the directory adapter with L11, use L03's one Catalog runtime and publish sample content through the opt-in fixture. The feature already calls `useSession`/`authenticatedRequest`; published dependency source copies remain uncommitted until their owning changes land. Verify private saves, reload, locale change and image attachment in the real browser as an actual signed-in buyer in both languages/themes at desktop and phone widths. Verify stale/unsupported requests via the actual owning-service APIs. No fixture transport or simulated session may count toward this gate.
