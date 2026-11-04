# Beirut Time

Lebanon’s independent watch marketplace: nine isolated FastAPI domains and one bilingual Next.js app. Beirut Time connects buyers with independent sellers; it owns no stock and performs no watchmaking.

## Local development

Starting the app requires Docker with Compose 2.20+ (merged `include` support). Local verification also uses Python 3.11+ and curl; host-side web editing uses Node 22 and Corepack.

```sh
make dev
# http://localhost:3000/en   http://localhost:3000/ar
make smoke
make test
make stop
```

The first start downloads dependencies, initializes one PostgreSQL instance with nine restricted logical databases, applies migration jobs, then waits for all runtime health checks. Data persists in the project volume; stopping does not delete it. Do not reset shared domain data to repair a migration.

Ports bind only to loopback. Default database passwords are **local-only development values**, not production configuration. Override `POSTGRES_PASSWORD`, `<SERVICE>_DB_PASSWORD` and `<SERVICE>_OWNER_PASSWORD` in an untracked `.env` before first initialization. Changes afterward do not rotate existing PostgreSQL passwords. Bootstrap/migration credentials never enter application containers.

| Runtime | Port | Database |
|---|---:|---|
| identity | 8101 | bt_identity |
| catalog | 8102 | bt_catalog |
| auction | 8103 | bt_auction |
| pricing | 8104 | bt_pricing |
| orders | 8105 | bt_orders |
| eligibility | 8106 | bt_eligibility |
| trust | 8107 | bt_trust |
| communications | 8108 | bt_communications |
| service-operations | 8109 | bt_service_ops |
| web | 3000 | none |
| PostgreSQL | 54329 | separate logical databases |

Service Operations uses the `SERVICE_OPS_*` credential prefix. Every Python runtime exposes `/health/live`, `/health/ready` and `/openapi.json`. Readiness checks its own schema/checksums only, not siblings. Web liveness is `/api/health`; web/mobile status compositions are `/api/web/v1/status` and `/api/mobile/v1/status`.

Start only the runtime needed for a local change; retain the shared PostgreSQL instance while other domains use it:

```sh
./infra/foundation/dev.sh identity web
python3 scripts/test-services.py identity
# Host-side web edits, with private services still in Compose:
corepack pnpm install --frozen-lockfile
corepack pnpm --filter beirut-time-web dev --port 3001
```

The frontend reads `<SERVICE>_API_URL` at runtime (loopback service ports by default outside Docker). Set `BT_PUBLIC_WEB_ORIGINS` to comma-separated exact public HTTP(S) origins when using another published port or deployed URL (for example `http://localhost:33101,https://your-public-domain`). Defaults are `http://localhost:3000,http://127.0.0.1:3000`; an explicit empty value disables configured origins. Internal bind addresses never establish browser trust. Keep `BT_TRUST_FORWARDED_ORIGIN=false` unless an edge overwrites both forwarded host/protocol headers and prevents direct access; fixed public origins do not require forwarded-header trust. Python processes use `BT_DATABASE_URL`, `BT_SERVICE_NAME`, `BT_DATABASE_POOL_SIZE`, `BT_MODULES_PATH`, `BT_LOG_LEVEL`, `BT_AUTH_PUBLIC_KEY`, `BT_AUTH_ISSUER`, `BT_AUTH_AUDIENCE` and `BT_SERVICE_AUTH_PUBLIC_KEY`. Missing verification keys fail closed. A valid token signature is identity, not a grant to a domain record.

## Parallel domain extension

**[The frozen extension contract](infra/foundation/README.md)** documents complete examples and ownership. Its key seams are:

- `infra/foundation/compose.sh` discovers existing `infra/compose/L00.yaml` … `L11.yaml` files and selects them into `compose.yaml`’s merged include. Each lane creates/edits only its own fragment; absent lanes use an L00-owned empty fallback. L00 supplies generic health-only fallbacks; one owning lane replaces each actual service runtime under `services/<service>/runtime/` using `services/_template/runtime/`.
- `services/<service>/modules/**/module.json` discovers module-owned routers, authorization, immutable migrations and opt-in fixtures without a central import edit. All modules of one service join the same runtime/database. New dependencies change foundation manifests, not a module install script.
- `packages/contracts-core/` defines Money, actor/org, revision, operation, error and event contracts. Domain contracts live only in `packages/contracts-<domain>/<module>/`, discovered through `contracts/registrations/Lxx.json`. Shared Python packages are `packages/runtime/`, `packages/events/` and `packages/bulkheads/`.
- `web/registrations/Lxx.ts` contributes unique public URLs, navigation, permitted roles, feature-local EN/AR dictionaries, styles, gateway namespaces and optional detail/dashboard slots. Adding the file is enough; the dev/build/typecheck step discovers it.
- Domain pages stay in the exact route groups from the lane plan, e.g. `web/app/(browse)/watches/`. Locale-prefixed URLs rewrite to this one tree; no duplicate `[locale]` route implementation is needed. Common shell/UI/i18n are immutable consumer APIs.
- Tests live in the owned module or `tests/lanes/Lxx/`. Only the integration owner writes `tests/integration/sprint-1/`. Demo fixtures use real authorized operations, label demo content and never seed a paid/winning/passed transaction.

No cross-service SQL, imports, shared schema file, global nav-array edits or arbitrary URL proxy is allowed. Navigation/registration never replaces server authorization.

## Reliability and privacy

The migration job owns DDL and immutable checksums under an advisory lock. Runtime roles cannot create tables, modify the migration ledger, or connect to sibling databases. Tests exercise negative role boundaries. The shared PostgreSQL instance is one physical failure domain, not nine independently highly available clusters.

A unit of work binds domain writes, audit/event intent and inbox receipts to one connection/transaction. Outbox delivery is **at least once**, leased and fenced per destination; consumers deduplicate business work atomically. HTTP delivery happens outside SQL transactions. The opt-in event receiver validates service-token purpose, audience, producer and event type; no public event bus is enabled.

Dependency-owned timeouts, connection/concurrency budgets and circuit breakers shed saturated calls without unbounded queues. Optional UI sections show unavailable independently. Money, stock, consent, payment and permission must never fall back to invented success.

Errors use `{ "error": { "code", "message", "request_id", "details" } }`. `X-Request-ID` follows each request. Structured logs contain route templates, timings and opaque references, not query strings, rejected inputs, credentials or request bodies. Nested local `.env` files are excluded from Git and Docker build contexts; safe `.env.example` templates remain eligible.

## Design and phone behavior

English/Arabic and the saved light/dark preference are stamped by the server before paint. Locale switching preserves the current public route/query. Feature dictionaries and styles stay local. Shared primitives adapt Creator Pipeline F-01, F-13, F-33–41 and F-73 without its product workflows.

The single phone shell breakpoint is **850px**. One persistent inner scroller sits between a header and a safe-area-aware bottom row; a modal menu replaces desktop navigation. Hit targets are at least 44px, with 36px painted buttons; input text remains at least 16px. Logical CSS and isolated LTR references support Arabic. Non-secret same-user draft conveniences are scoped and purged on identity/access changes; credentials and private evidence must never enter web storage.

Localized manifests, 192/512px/maskable icons, progressive installation, offline notices and user-consented updates make the app installable. The worker caches only public same-origin static assets—not HTML, API, RSC or private responses. Offline bids/purchases are never queued or confirmed. Physical iPhone/Android installation, keyboards and assistive technology remain separate from browser emulation.

## Validation

`make smoke` builds, starts and probes all nine runtimes, web, both locales/themes and live BFF readiness. It stops only application containers it started unless `KEEP_RUNNING=1`; `SKIP_BUILD=1` reuses images. The shared PostgreSQL process is preserved across lane checkouts. `make test` runs domain proofs against unique disposable `bt_test_<uuid>` databases with isolated owner/runtime roles and runs TypeScript, ESLint and web unit/worker tests. Tests never migrate, write to or reset ordinary domain databases. Test images have per-run tags to avoid collisions between lane checkouts.

`python3 infra/foundation/origin-smoke.py` checks configured public origins across a Docker-published port, explicitly trusted edge headers and a real browser POST, using a synthetic transport-only upstream. `python3 infra/foundation/context-smoke.py` proves nested local environment files cannot enter a Docker context. `python3 infra/foundation/proxy-smoke.py --loopback --browser` builds an isolated production image with synthetic registered nested routes and checks locale rewrites, single-hop redirects and exact desktop/phone geometry; fixture routes never enter the normal app build.

The real-browser matrix checks both locales/themes at desktop and phone widths, focus, menu behavior, layout fit and independent dependency failure. Actual evidence and limits are recorded in [docs/validation.md](docs/validation.md). No hosted validation workflow is required.
