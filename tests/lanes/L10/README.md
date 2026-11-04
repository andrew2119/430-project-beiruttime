# L10 verification

Run `./tests/lanes/L10/verify.sh` from an isolated checkout with the pinned pnpm shim on PATH. It reuses a cached lane image with current source mounted read-only, verifies third-party dependency pins, exercises real PostgreSQL transactions and restricted credentials, runs Python static checks, whole-web lint and typecheck, builds Next.js and runs foundation and feature web tests. Set `L10_TEST_IMAGE` to select a cached image; use `L10_REBUILD_IMAGE=1` only when dependencies actually change. Shared PostgreSQL is preserved. Every proof creates and drops its own database and roles; ordinary domain databases are never migrated by this suite. Finished proof containers remain stopped, never pruned.

`BT_MODULES_PATH=/tmp/l10-core-baseline` keeps generic migration proofs on their core-only starting schema. L10 tests explicitly migrate their own modules into disposable databases before invoking real owning-service routes.

Coverage includes all four stories, exact revision boundaries/types, owner and selected-organization scope, unavailable dependencies, unsupported/foreign options, unavailable material and stale snapshots, duplicate/concurrent operations, restart recovery, safe and unsafe PNGs, private file access and cross-configuration attachment, integer price references, transactional outbox intent, the released paginated Directory V1 contract and exact Identity business authority. The catalog budget counts `(kind,id)`, not just IDs; existing revision updates remain possible when full.

## Transport-fixture public proof

`tests/lanes/L10/compose.yaml` is intentionally **not** included in root composition. Its default `catalog-proof` server uses real migrations, PostgreSQL and owning-service commands. Identity and directory transports are explicitly deterministic fixtures, never production fallback behavior.

```sh
docker compose -f tests/lanes/L10/compose.yaml up -d --no-build catalog-proof
BT_PUBLIC_WEB_ORIGINS=http://localhost:3110,http://127.0.0.1:3110 BT_TRUST_FORWARDED_ORIGIN=false CATALOG_API_URL=http://127.0.0.1:9110 web/node_modules/.bin/next start web --port 3110
```

This requires an existing lane test/browser image. Open `/en/customize?brand=20000000-0000-4000-8000-000000000001&base=atelier-38&caliber=manual-01` and its Arabic equivalent. Run `browser-proof.js` through the browser CLI with desktop 1440px, then `emulate --viewport 390x844x3,mobile,touch`. Assert `innerWidth===390`; desktop resizing can silently clamp to 500px on this Mac.

## Connected isolated proof

Copy the published L01 Identity runtime/account screen/session/gateway, L02 business/membership modules and L11 Directory source into their owning paths **without committing those copies**. Use main's owning versions after merge. With cached Python dependencies present:

```sh
docker compose -f tests/lanes/L10/compose.yaml --profile live up -d --no-build connected-proof
```

`live_server.py` starts real Identity, Service Operations and Catalog HTTP applications with three separate disposable PostgreSQL databases/restricted roles. It uses the foundation modular runtime for the Catalog proof, not a competing production Catalog runtime; L03 remains the runtime owner. The only direct authority setup is an isolated operator grant. Real account registration, operator business onboarding, colleague membership, fresh staff login after session revocation, Directory publication and all sample option publication run through the actual APIs. No transport fixture is installed. The ready line supplies the newly onboarded sample brand ID.

Start the production web server with the previous origin settings plus `IDENTITY_API_URL=http://127.0.0.1:9121`. Register a buyer through the actual account screen, then open `/en/customize?brand=<ready-id>&base=atelier-38&caliber=manual-01`. Run `connected-browser-proof.js` once at 1440px and again with exact phone emulation. It saves every category in both languages/themes, asserts strictly advancing acknowledged revisions and reloads the same private configuration across locale/viewport navigation. No token or cookie is injected by the proof. Run `private-reference-browser-proof.js` to supply a labeled synthetic 1px PNG through the actual input change handler, save a dial choice and verify the authenticated private image and unchanged saved revision after full reload in both languages. The native browser upload command on this Mac did not dispatch the application's change event; this explicit File/DataTransfer route tests the real handler, not a mocked upload response.

For native pixels, use isolated headless Chrome and the browser CLI for navigation/emulation, then `node tests/lanes/L10/capture-native.mjs <debug-port> <output.png>`. Whole-viewport capture avoids manual clip offsets in emulated RTL. A screenshot path reported by the browser CLI alone does not prove a file was written.

Stop only these proof services with `docker compose -f tests/lanes/L10/compose.yaml --profile live stop`. Graceful shutdown drops their databases. Do not remove containers or stop the shared PostgreSQL instance.

## Results (2026-11-04)

- After merging foundation and accounts main: 98 Docker/PostgreSQL tests, no skips, one upstream Starlette deprecation warning; Python static checks passed. Includes strict authority types, preserved 401 refresh semantics and the signed Communications inbox-path transport proof (not real receiver acceptance).
- Production build/type check with the current published L01 source: passed; 66 foundation and 27 feature web tests passed. Contract discovery and Compose validation passed.
- Real Chrome live-HTTP authenticated matrix: 32 saves (four categories × English/Arabic × light/dark × 1440px/390px), exact phone DPR3, no horizontal overflow, 44px selects, 16px phone input text, sample labels, no approval/submission claims. All four choices reopened across locale changes and full navigation.
- Safe PNG upload, authenticated private image decoding and a subsequent dial save worked against the real connected services; private image survived full reload. Credentials stayed in the current Identity SDK/cookie flow.
- Earlier public signed-out matrix: 32 checks, disabled saving and honest unavailable recovery. Production GET/HEAD on both loopback hostnames returned 200 without redirects in both languages; nested environment exclusion passed. Native desktop English and phone Arabic pixels were visually reviewed in both themes.

The latest main also includes auction/discovery code whose Pricing quote DTO is not yet on main; the published L06 TypeScript contract was copied uncommitted to complete the production build. The live proof uses main's actual L01 account/session source and published L02/L11 owning source before those dependent branches merge. Recheck against the merged L01/L02/L03/L11 launcher/runtime after integration. Communications event allowlisting/delivery remains a separate dependency: these proofs establish durable pending intent, never notification receipt or business approval.

## Derived-state regression check

The follow-up removes synchronous effect state mirrors: SDK session status is read directly, the private query snapshot owns saved bindings/references, and private image results are scoped to owner/resource/retry identity. Only genuine async completion updates image state. Private PNGs use an unoptimized memory-only image source, never a public optimizer request.

Whole-web lint and typecheck, production build, 98 PostgreSQL tests, 66 foundation web tests and 34 feature tests passed on main `d34b74d` plus the released uncommitted Pricing DTO. Seven render regressions cover restoring/unavailable/signed-out states, immediate canonical snapshots, stale URL bindings and private-owner fencing. Live HTTP browser checks repeated all 32 saves, private PNG reload in both languages, new/resumed configurations, and automatic canonical recovery after intentionally losing a successful save response. The last proof changes only that browser's transport acknowledgement after the real backend commits; no success is fabricated. All proof services stopped with isolated database cleanup confirmed.
