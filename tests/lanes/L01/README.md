# Identity and private-consent proofs

## Run the services

Use the shared local PostgreSQL instance through the foundation launcher. Run only the two owned services; do not reset domain databases.

```sh
bash tests/lanes/L01/local-keys.sh
set -a; source tests/lanes/L01/local-config.key; set +a
export BT_WEB_ORIGIN=http://localhost:3101
export BT_ALLOWED_WEB_ORIGINS=http://localhost:3000,http://localhost:3101,http://localhost:3077
export BT_PUBLIC_WEB_ORIGINS="$BT_ALLOWED_WEB_ORIGINS"
export BT_TRUST_FORWARDED_ORIGIN=false
./infra/foundation/dev.sh identity eligibility
corepack pnpm --filter beirut-time-web build
corepack pnpm --filter beirut-time-web start --port 3101 --hostname localhost
```

Generated configuration/signing files are ignored by both Git and Docker. The origin allowlist is exact, never a wildcard. Bind the local Next process to `localhost` for this preview. `BT_PUBLIC_WEB_ORIGINS` supplies the exact public browser origins independently of an internal bind host/port; this also supports Docker-published ports. The gateway forwards the origin only after its configured-origin check. Identity independently enforces its own exact allowlist; never trust forwarded headers on a directly reachable local server.

## Automated proofs

```sh
BT_TEST_LANE=L01 python3 scripts/test-services.py identity eligibility
ruff check services/identity/modules services/identity/runtime/service_app services/eligibility/modules services/eligibility/runtime/service_app tests/lanes/L01 --select E9,F
corepack pnpm --filter beirut-time-web typecheck
corepack pnpm --filter beirut-time-web lint
corepack pnpm --filter beirut-time-web test
corepack pnpm --filter beirut-time-web exec vitest run -c features/identity/vitest.config.ts
python3 infra/foundation/context-smoke.py
python3 tests/lanes/L01/verify-build-context.py <owned-proof-image-tag>
```

The backend runner creates disposable databases and restricted roles per proof and removes them afterward. It never migrates or clears an ordinary service database. Test-side direct SQL is restricted to these disposable fixtures (review assignments, simulated current grants, precise expiry and suspension boundaries). Real browser demonstrations use application operations rather than fixture SQL.

The Identity suite covers registration/restart, duplicate races, no self-granted business authority, live principal scope, session rotation/replay/logout races, password and one-use reset revocation, expired reset links, explicit mailbox capability, exact configured origins, purpose/session/recipient-bound contact reauthentication with transactional rollback, private evidence assignment and current-permission fences, stale corrections, byte bounds and cancelled-KDF capacity retention. Eligibility covers purpose/version/request binding, concurrent idempotency, refusal without evidence, dependency outages without writes, assigned non-self reviewers, withdrawal immediately denying bytes, strict revision/subject-bound service acknowledgements, deduplication and durable recovery.

## Browser demonstration

1. Open `/en/account`. Register with synthetic information, or sign in to an existing synthetic buyer. No business/operator role can be requested at registration. An allowlisted `next` destination returns to the intended action after sign-in.
2. Open `/en/seller/verification`. Use the included synthetic text files and a `DEMO-...` payout reference. Submission creates a real private case and private byte records. Its initial state is **pending**, not approved and not a physical watch inspection. Correction and approval belong to the authorized review workflow.
3. Prepare an actual private brand request through the request service. Open `/en/consent?request=<id>&brand=<id>&revision=<revision>`. Explicit agreement stores bounded private evidence only after the request owner/brand/revision contract passes; refusal stores no evidence. No check, payment or production grant is implied.
4. Withdraw an active consent. It becomes locally ineffective immediately, and the page truthfully remains `withdrawal_pending` until both owning consumers acknowledge their fences. Never forge these acknowledgements for a demonstration.
5. Change language/theme and reload. Server-acknowledged records survive. Credentials and evidence do not enter browser storage. Sign-out and account switches purge the prior access context; long-running file preparation is owner-fingerprint fenced before any mutation.

If the request service is absent or does not recognize a reference, consent must fail closed. This is an unavailable/denied state, not a fixture success.

For the visual/geometry matrix, use an isolated browser session and assert the real viewport. A resize request can be clamped by the desktop window manager.

```sh
mkdir -p tests/lanes/L01/artifacts
export CHROME_DEVTOOLS_AXI_SESSION=bt-l01
chrome-devtools-axi emulate --viewport '390x844x3,mobile,touch'
chrome-devtools-axi run < tests/lanes/L01/browser-matrix.js > tests/lanes/L01/artifacts/phone-matrix.json
chrome-devtools-axi emulate --viewport '1440x900x1'
chrome-devtools-axi run < tests/lanes/L01/browser-matrix.js > tests/lanes/L01/artifacts/desktop-matrix.json
```

The matrix opens all three screens in both languages/themes, records the actual viewport/direction/theme, and checks clipping, horizontal overflow, input font floors and target geometry. Physical-device keyboard, installation and assistive-technology acceptance remain distinct from emulation.

## Provider contracts

Browser contract: `packages/contracts-identity/accounts/BROWSER.md`.

Identity sibling-module contract: `packages/contracts-identity/accounts/INTERNAL.md`.

Request-context and withdrawal-fence contract: `packages/contracts-eligibility/consent/README.md`.
