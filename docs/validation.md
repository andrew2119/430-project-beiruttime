# Foundation validation

Executed locally on 4 November 2026. These checks cover the foundation and its extension contract, not completed marketplace business workflows.

## Executed checks

- Docker builds the production web image and multi-stage non-root Python runtime. Compose starts nine independently configured fallback runtimes, nine isolated logical databases, successful migration jobs and a healthy web process.
- The one-command launcher and smoke test pass all live/readiness endpoints, English/Arabic markup, light/dark cookies and all nine BFF readiness results. A configuration-only lane override replaces the existing runtime/migrator image without adding another authority; absent lane files remain optional. The lane-local launcher preserves the existing PostgreSQL container id even when the checkout’s Compose metadata changes.
- **21 Python proofs per runtime × 9 runtimes = 189 passing cases.** Coverage includes checksum refusal, atomic module migration failure, real restricted runtime roles, sibling/maintenance database denial, transaction rollback, concurrent inbox deduplication, independently retried outbox fan-out, destination-scoped relay claims and storage-free empty relays, released SQL locks during HTTP, service-token purpose/audience/producer checks, dependency saturation/timeouts/cancellation/circuits, exact Money, module/router discovery, pure hooks, request-body caps, private-file authorization ordering, organization-scoped permissions, stable public error codes/details and redacted policy denials.
- The final principal-status fix passes **7 targeted runtime-boundary cases**, including real FastAPI HTTP/error-envelope checks for both Identity 401 and 403, using current source mounted read-only into an existing test image. No image rebuild or ordinary database access was needed. Identity 401 becomes a safe public unauthorized error; authenticated denials remain redacted 403.
- Test databases and owner/runtime roles are unique and disposable. Application proofs use restricted credentials. Migration tests explicitly request owner credentials. The runner never applies migrations to ordinary domain databases, uses per-run image tags, and supports lane test selection without a central index edit. Missing consumer fragments/registrations/tests are not scaffolded into other lanes’ owned files.
- **66 web unit/behavioral tests pass**, including dictionary parity, registry uniqueness, Arabic/Persian digit normalization, gateway path safety, bounded dependency isolation, typed support references, private binary transport, same-session draft restoration, prior-user purge, real worker-source execution and validated Origin propagation for login/register/refresh. Foreign, opaque and missing mutation Origins are rejected before an upstream call; unvalidated read Origins are never forwarded. Runtime public-origin allowlists are independent of Next’s internal bind address; forwarded authority requires exact explicit opt-in, rejects chains/malformed values and is never implicitly trusted. Locale routing covers valid nested prefixes, preservation of URL locale over cookie locale, missing-prefix-only redirects, query preservation, a normalized `nextUrl` self-redirect regression and same-origin rewrites for raw IPv4/IPv6 loopback URLs. The config regression requires `skipProxyUrlNormalize`; changing only the proxy is insufficient. Eight gateway/client regressions preserve Identity/domain 401 versus 403 into `ApiError`, deny missing authentication and wrong roles before domain calls, and map unexpected Identity failures to unavailable rather than a refreshable authentication error.
- A separate production gateway image passes **18 origin cases** across an actual Docker-published port and explicitly trusted edge headers. A real browser’s POST reaches the synthetic metadata-only upstream with its validated public Origin; internal/foreign/opaque/missing Origins remain rejected. The test fixture implements no authentication operation, credentials or authorization stand-in.
- A real Docker context proof creates nested synthetic `.env`, `.env.local` and `.env.production` files and proves none survive `COPY .`; a safe `.env.example` remains available. Git exclusion is checked independently for the same paths.
- A separate production image registers synthetic nested `/operations/moderation` and `/seller/dashboard` routes, then proves prefixed requests return 200 with no Location and unprefixed requests redirect once, preserving queries. The normal production image never includes these fixture pages. This first proves the foundation routing seam without domain access guards. A second image overlays the exact published Auction and Moderation route groups, registrations and dependencies only inside its isolated test build. Both images run with Next bound to `127.0.0.1`, reproducing the original 307 loop before the fix and passing EN/AR GET/HEAD probes afterward. Host curl uses `--max-redirs 0`; already-prefixed routes return 200 without Location. The root cause was NextURL changing `127.0.0.1` to `localhost`, which made Next treat its own rewrite as an external request and re-enter the missing-prefix redirect branch.
- TypeScript, ESLint, Ruff and shell syntax checks pass. Production web dependency audit reports zero advisories. Starlette’s test client emits one upstream AnyIO deprecation warning; it does not affect the passing results.

## Real-browser matrix

`chrome-devtools-axi` drove the production container in Chromium, with actual emulated viewport dimensions (not just window resizing):

- English and Arabic × light and dark × 1440×900 desktop and 390×844 phone (phone DPR 3).
- Home and About in every combination: **16 page renders**, correct server language/direction/theme, all nine live availability states, no document or inner-scroller horizontal overflow.
- Phone header/preferences controls are at least 44px; bottom links are 48px tall. At 390px, the content frame is 374px wide and sits above a separate 60px navigation row.
- Both menu triggers, modal containment, Escape/trigger restoration, destination-main focus and route-preserving locale changes pass. A 30-entry Arabic menu at 320px retains a visible, uncovered close control. Explicit focus restoration also covers programmatic activation.
- Additional 320×664, 850×900, 851×900 and 932×430 landscape cases pass. The exact 850/851px navigation boundary closes the old drawer and transfers focus to main instead of a hidden control.
- The isolated nested-route production image additionally passes both routes × both locales × both themes × both viewports: **16 page renders**, registered-path markers, correct internal paths and no overflow. The exact Auction `/seller/auctions` and Moderation `/operations/moderation` pages pass the same matrix: **another 16 page renders**, without credentials or authority stand-ins. Viewport assertions require exactly 1440px desktop and 390px phone.
- Browser-computed foreground/muted/accent/button contrast is at least 4.5:1 in both themes; input boundaries exceed 3:1. The active worker cache stays within 160 entries with no HTML/API/private entries. Request-log probes retain the support id and route template without recording a synthetic private query marker.
- A real communications-container outage leaves the shell and catalog available, returns one typed unavailable sub-result, produces the standard 503 support-reference envelope, and fits at 320px. Restart and circuit recovery return all nine services to ready.

The module-migration proof also passes with a pre-registered service migration inventory. Its synthetic migrations use a fresh core-only database, preserving both atomic-rollback and checksum-tampering assertions; normal fixtures still apply service modules.

Reproduction commands:

```sh
KEEP_RUNNING=1 ./scripts/smoke.sh
python3 scripts/test-services.py
BT_MODULES_PATH=/foundation-tests/fixtures/registered-module python3 scripts/test-services.py identity
BT_TEST_LANE=L00 python3 scripts/test-services.py identity
corepack pnpm --filter beirut-time-web typecheck
corepack pnpm --filter beirut-time-web lint
corepack pnpm --filter beirut-time-web test
./infra/foundation/browser-smoke.sh
./infra/foundation/outage-smoke.sh
python3 infra/foundation/origin-smoke.py
python3 infra/foundation/context-smoke.py
python3 infra/foundation/proxy-smoke.py --loopback --browser
# Optional: a local web/packages overlay assembled from published domain contracts only.
python3 infra/foundation/proxy-smoke.py --overlay artifacts/lane-route-overlay --loopback --browser
```

The outage script refuses to stop another checkout’s container or a domain-owned runtime. Browser JSON and transient logs remain under ignored `artifacts/` / log files, not in the shared source snapshot.

## Known boundaries

The nine L00 fallbacks serve health and infrastructure only. Listing, bid, checkout, payment, identity-session and business transition implementations belong to the registered domain modules; the foundation does not fabricate them. The illustrated watch is not inventory. Browse remains disabled until its real domain route is registered; informational navigation works without pretending the marketplace flow exists. Private workspace frames do not authorize access or display private records by themselves.

Service-token ingestion is opt-in and fail-closed; no public bus is enabled. Token signatures do not replace current permissions, represented organization and resource ownership. Module code must use its own scope and transaction guards.

The PWA is online-first: no private worker cache or offline write queue. Physical iOS/Android installation, real keyboards/notches, VoiceOver/TalkBack and floor-version browser acceptance remain unverified. Emulated Chromium geometry and keyboard focus do not establish those physical-device results. No external-provider, production hosting or legal financial-custody claim is made.
