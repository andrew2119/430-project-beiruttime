# Frozen foundation extension contract

Each lane changes only its registration, fragment, module/feature subtree and tests. Shared shell files, workspace manifests and generated indexes are not consumer edit points.

## 1. Compose and runtime ownership

`infra/foundation/compose.sh` discovers existing `infra/compose/L00.yaml` … `L11.yaml` files and selects them into `compose.yaml`’s **one merged include list**. Later fragments override earlier definitions. Missing lanes use `infra/foundation/empty.yaml`: L00 never creates or commits another lane’s fragment, registration or test placeholder. Use the launcher for all lane-aware Compose commands, e.g. `./infra/foundation/compose.sh config` or `./infra/foundation/compose.sh ps`. `L00` supplies PostgreSQL, web and nine **generic health-only fallback runtimes**, all built from `services/_template/`. It does not implement domain services. A runtime-owning lane replaces the same named runtime and migration image in its fragment; it must not introduce another authoritative process for that domain.

| Lane | Runtime(s) |
|---|---|
| L01 | identity, eligibility |
| L03 | catalog |
| L05 | auction |
| L07 | pricing, communications |
| L08 | orders |
| L09 | trust |
| L11 | service-operations |

Create only an owned runtime with `./infra/foundation/new-runtime.sh identity`. Copying refuses an existing runtime and preserves modules other lanes may already have added. Then write the following **in your own fragment**, once per runtime and migration job:

```yaml
services:
  identity:
    image: beirut-time/identity:local
    build:
      context: .
      dockerfile: services/identity/runtime/Dockerfile
      args:
        SERVICE_PATH: services/identity
  identity-migrate:
    image: beirut-time/identity:local
    build:
      context: .
      dockerfile: services/identity/runtime/Dockerfile
      args:
        SERVICE_PATH: services/identity
```

Database roles, ports, environment and readiness ordering inherit from L00. Use `./infra/foundation/dev.sh identity web` for lane-local development: it preserves an already-running PostgreSQL process, applies only selected runtime migrations and starts selected containers without recreating dependencies. The no-argument launcher is for the complete integration checkout. Do not run a partial lane’s migrations against a database whose other module code has not been integrated. The build context is the repository root. One image includes **all modules of that one service**. No module edits a Dockerfile or shared manifest. Dependencies already available are FastAPI, Pydantic, asyncpg, HTTPX, PyJWT/cryptography and the four shared Python packages. Declare existing dependencies in module metadata; new dependencies require a foundation manifest change.

Service Operations is named `service-operations`; its existing logical database/credential slug is `bt_service_ops` / `SERVICE_OPS_*`. This is a single runtime/database, not another domain.

## 2. Service-local modules

Place `module.json` anywhere below `services/<service>/modules/`:

```json
{
  "version": 1,
  "id": "L01.accounts",
  "dependencies": ["fastapi", "asyncpg"],
  "routes": ["routes.py:router"],
  "authorization": "authorization.py:authorize",
  "migrations": ["migrations/L01_0001_accounts.sql"],
  "fixtures": {"demo": "fixtures.py:seed"}
}
```

- Each router exports an ordinary FastAPI `APIRouter`. Use relative Python imports inside the module. Runtime discovery supplies a private package namespace; no central import edit is needed.
- `authorization` is an optional FastAPI dependency applied to every route in that module. Omit it only for explicitly public routes whose private commands have their own guards. Duplicate method/path registrations fail boot.
- Optional `"workers": ["workers.py:run"]` declares bounded async callbacks `(app, stop_event)` supervised by the runtime lifespan. Workers retry failures with backoff and are cancelled during bounded shutdown. They must use durable leases/idempotency for replica-safe work; no import-time task creation or background success simulation.
- Optional `"hooks": {"auction.proxy.v1": "proxy.py:calculate"}` contributes a synchronous pure callback to `app.state.hooks` without runtime import edits. Duplicate names and async hooks fail boot. L05 owns/finalizes its typed signature and invokes that L06 callback **inside its one bid unit of work**, without passing commit ownership. L06 must not start another transaction or bid engine. The generic loader provides the hook seam, not proxy pricing logic.
- Entry points and migration paths must resolve inside the module. Migration names carry the lane and a four-digit monotonically ordered sequence. Module id + file name form an immutable checksum ledger key. Core migrations run first, then modules in deterministic id order. Do not modify an applied migration.
- `bt_runtime.app.db.unit_of_work(pool, lock_key=...)` binds repository writes, inbox receipts and event intent to one transaction. Readiness validates the entire current migration set. Only the separate migration job gets owner credentials.
- Domain handlers enforce current permission, object ownership, represented organization, expected revision and idempotency. Registration is not authorization.
- No cross-service Python imports or SQL. Each image includes one service’s modules; use versioned HTTP/events for other services.

`services/_template/module-example/` is a deliberately disabled example, **not loaded** by the fallback runtime. Copy it into your owned module subtree and rename its id/migrations. It grants no business permission and seeds nothing.

## 3. Contracts

`packages/contracts-core/` exports Python `bt_contracts_core.models` and TypeScript `@beirut-time/contracts-core`:

- exact decimal-string `Money` in USD/LBP (no binary floats), Actor/org scope;
- Revision, pending/succeeded/denied/unavailable Operation;
- standard ErrorEnvelope and versioned EventEnvelope.

A domain owns only `packages/contracts-<domain>/<module>/`. Register its files/fixtures in `contracts/registrations/Lxx.json`:

```json
{"version":1,"lane":"L01","contracts":[{"namespace":"identity.accounts.v1","path":"packages/contracts-identity/accounts","fixtures":["packages/contracts-identity/accounts/fixtures/session.v1.json"]}]}
```

`python3 infra/foundation/discover-contracts.py` validates registrations and outputs their discovered inventory. The web build discovers these same files. No global index is hand-maintained. TypeScript can import a source contract via `@contracts/contracts-identity/accounts`; Python contracts are ordinary modules in that subtree, included in images as `bt_contracts.identity.accounts`. Contract changes belong to the provider; breaking changes require a new version, not a consumer patch.

## 4. Web registrations

Root-owned infrastructure rewrites `/en/...` and `/ar/...` to the same App Router route tree. Keep `web/next.config.ts`’s `skipProxyUrlNormalize` enabled together with the standard-URL rewrite in `web/proxy.ts`: NextURL changes loopback IPs to localhost, which can turn a same-origin rewrite into an external self-request and redirect loop when the development server binds `127.0.0.1`. Your route group stays exactly where the lane plan names it, e.g. `web/app/(browse)/watches/page.tsx`; do **not** add a competing `[locale]` tree. URL groups are not namespaces. Use distinct `/watches`, `/buyer`, `/seller/dashboard`, `/seller/listings`, `/seller/auctions`, `/operations/dashboard`, `/operations/moderation`.

- Server locale: `getLocale()` from `@/shell/locale`.
- Client locale: `useLocale()` from `@/shell/locale-context`.
- UI primitives: `@beirut-time/ui`; `BidiReference` isolates LTR identifiers.
- Common copy/digit normalization: `@beirut-time/i18n`.
- Generic account/seller/operator composition frames: `@/shell/layouts`. These do **not** replace Identity’s authenticated boundary.

Add only `web/registrations/Lxx.ts` (default export typed `Registration` from `@/registry-types`):

```ts
import en from '../features/discovery/en.json';
import ar from '../features/discovery/ar.json';
import '../features/discovery/styles.css';
export default {
  lane: 'L04', namespace: 'discovery',
  routes: [{path:'/watches',roles:['public'],area:'storefront'}],
  navigation: [{id:'watches',href:'/watches',label:{en:'Watches',ar:'الساعات'},order:10,area:'storefront',roles:['public'],bottom:true}],
  dictionaries: {en,ar},
  gateway: [{service:'catalog',path:'/v1/listings',methods:['GET'],roles:['public']}],
  slots: []
} satisfies import('../registry-types').Registration;
```

The dev/build/typecheck scripts discover files automatically. Duplicate URLs, namespaces, nav ids, slot ids or mismatched locale keys fail validation. Feature dictionaries and CSS stay in the **owned feature directory**. `featureMessages(namespace,locale)` and `slotsFor(target)` resolve registered contributions; slot loaders return `{default: ComponentType<SlotContext>}` for `watch.detail`, `buyer.dashboard`, `seller.dashboard` or `operator.dashboard`. A shell/slot composes current DTOs, never a second business state machine.

Navigation is a display affordance, not a security boundary. Role-sensitive routes must use the authenticated provider and domain authorization. The public foundation shows public entries only. Locale switching preserves the public path/query and non-secret same-user drafts using `@/shell/private-state`; verified Identity must call `setAccessContext(fingerprint, roles)` on restore/change/logout. Use a non-secret one-way access fingerprint covering subject, session lineage, represented organization and access revision; never persist raw tokens or private evidence. That clears prior-user query state and draft conveniences; credentials/private evidence must never enter web storage. Server-acknowledged drafts remain authoritative.

## 5. Gateway

Registered namespace routes are `/api/{web|mobile}/v1/<service>/v1/...`. The gateway matches only declared method/path patterns (`:id` matches one bounded segment); it is not an arbitrary URL proxy. It preserves Authorization, Idempotency-Key, If-Match, locale and request id, rejects cross-origin mutations, caps bodies, and uses a separate deadline/concurrency/circuit budget per upstream. Endpoint registrations may set `maxBodyBytes` and `maxResponseBytes` (hard maximum 16 MiB; defaults 1 MiB/2 MiB). A runtime owner can set `BT_REQUEST_BODY_LIMIT` for its matching domain upload budget; domain stores must enforce bounded reads.

Only a validated public browser Origin is forwarded upstream. Set runtime `BT_PUBLIC_WEB_ORIGINS` to exact comma-separated public HTTP(S) origins, including a nonstandard published port. Defaults are `http://localhost:3000,http://127.0.0.1:3000`; an explicitly empty value disables configured origins. The internal Next bind address, port and caller-supplied Host never grant trust. Wildcards, opaque origins, credentialed URLs and path/query/fragment values are not accepted. Mutations require this validation before forwarding, so Identity can enforce its own CSRF boundary without trusting an arbitrary supplied header.

Forwarded authority is ignored by default. `BT_TRUST_FORWARDED_ORIGIN=true` additionally trusts one exact `X-Forwarded-Host` plus `X-Forwarded-Proto` public origin; enable this **only** when an edge overwrites both headers and prevents direct access to Next. Do not enable it merely because a deployment uses a proxy: an explicit public-origin list works without header trust and is preferable when the public URLs are fixed. Comma-separated chains, incomplete headers and non-HTTP(S) protocols are rejected. Origin remains mandatory for mutations even behind a trusted edge. Configure Identity’s own origin policy consistently; the gateway does not bypass it.

For non-public registrations it asks Identity `GET /internal/v1/principal` with the Bearer token. The shared shape is `CurrentPrincipal { actor, roles, permissions, organizations, organization_grants }` in `bt_runtime.principal`. `permissions` are platform/individual permissions only. Business permissions are in `organization_grants[{organization_id,permissions,roles}]`; `require_scope` also requires the verified actor’s selected organization and membership to match. A permission in one business never combines with membership in another. The destination service still verifies identity, current permission and ownership. `current_principal` preserves Identity’s 401 as a safe public unauthorized error; a verified identity without permission remains 403. The gateway and typed client keep those statuses distinct so Identity’s session layer can refresh only an authentication failure, never a permission denial. Unexpected Identity failures are unavailable, not expired-session signals. An unavailable identity check cannot grant access. Cookie forwarding is opt-in, by exact `forwardCookies` names, and only for Identity; Identity owns refresh/cookie security. No caller-supplied actor/organization header is trusted.

## 6. Events, private files and tests

Use `bt_contracts_core.errors.PublicError(code, message, status=..., details=...)` for deliberately public, stable command outcomes. `AccessDenied` marks policy denial and maps to a redacted 403; operating-system errors remain internal. The typed web `ApiError` retains safe `details` and support references for field corrections. Never wrap arbitrary exception text as a public message.

`bt_events.enqueue/consume/OutboxRelay` use the V1 envelope from contracts-core and independent destination leases. Supply authenticated delivery headers. Each relay claims only rows whose destination is present in its own clients map, before ordering/limiting or acquiring a lease; other destinations retain their attempts, lease and backoff unchanged. An empty clients map is a storage-free no-op. A module may expose `bt_runtime.event_http.build_event_router(...)`; this opt-in receiver checks an RS256 **service** token against `BT_SERVICE_AUTH_PUBLIC_KEY`, exact service audience, producer identity and allowed event type before transactional inbox work. User access tokens cannot publish events. No event endpoint is enabled by default.

`bt_runtime.principal.current_principal/require_scope` expose fresh principal/org checks. `bt_runtime.files.ScopedFiles` authorizes a domain resource before fetching private bytes from a domain-owned store; there is no shared private bucket.

Module tests live inside the module. `bt_runtime.testing` creates a unique disposable database **and restricted owner/runtime roles** per proof; `database_url` / `database_runtime_url` use the restricted role, while `database_owner_url` is explicitly for migration tests. The test runner never migrates an ordinary domain database and gives every build a per-checkout/per-run image tag. Synthetic migration-history tests opt into a separate core-only database with `@pytest.mark.parametrize('database_access', ['core-only'], indirect=True)`, rather than replacing the inventory of an already-migrated service database. Default fixtures still apply the real service modules. To exercise this regression, run `BT_MODULES_PATH=/foundation-tests/fixtures/registered-module python3 scripts/test-services.py identity`; the override names a path inside the test image. Shared PostgreSQL stays running for other lanes. Lane-level tests live under `tests/lanes/Lxx/`. Run `BT_TEST_LANE=L02 python3 scripts/test-services.py identity` to add that lane’s suite without changing a Dockerfile or index; core proofs and module tests always run. Multi-runtime lanes can split tests into `tests/lanes/Lxx/<service>/`, which the runner selects automatically. Only L08 writes `tests/integration/sprint-1/`.

Fixtures are opt-in (`python -m bt_runtime.fixtures L01.accounts demo`), never startup seeds. Their callable receives Settings and must use real authorized application operations. L03 alone owns real demo listing/media import. No fixture may seed a winning bid, paid order, independent pass, receipt or payout.

Auction proxy calculation and Orders allocation are domain-owned contracts (L05/L06 and L08); the foundation supplies their transport/transaction seams, not another bid engine or sale fence.
