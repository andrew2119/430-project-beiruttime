# L07 verification

## Commands

- `BT_TEST_LANE=L07 python3 scripts/test-services.py pricing communications`: isolated PostgreSQL databases/roles; Docker domain and foundation proofs.
- `./infra/foundation/dev.sh pricing communications`: build real production images, apply module-local migrations, start the two runtime owners. Preserve shared PostgreSQL; stop only these two containers after a local run.
- `pnpm --filter beirut-time-web build`: integrated production build and TypeScript against the merged canonical Identity provider. The scoped `tsconfig.json` fixture remains useful only for contract-isolation checks.
- `pnpm --filter beirut-time-web exec vitest run --config "$PWD/tests/lanes/L07/vitest.config.ts" --root "$PWD"`: exact localized money parsing/display.
- `BT_BROWSER_ORIGIN=http://127.0.0.1:3177 bash tests/lanes/L07/browser-matrix.sh` against the integrated production app: canonical Account registration, logout/sign-in and Consent navigation, then 24 authenticated route/locale/theme/width geometry observations under ignored `.runtime/`. It creates fresh synthetic buyers and saves real previews/drafts. Use a dedicated named Chrome session and stop it afterward. Screenshot output paths must be checked separately.
- Check the chosen port with `lsof -nP -iTCP:3177 -sTCP:LISTEN`, bind explicitly to `127.0.0.1`, and configure exactly the same origin in the isolated Identity `BT_ALLOWED_WEB_ORIGINS`/`BT_WEB_ORIGIN` and web `BT_PUBLIC_WEB_ORIGINS`. Do not stop another process using a conflicting port.

No fixture grants authority or fabricates a successful transaction. HTTPX transports in service tests model independently versioned dependencies, and are never enabled by the application. The production application must be tested with the real Identity, Pricing, Communications and Orders APIs before final acceptance.

## Coverage

Q01: synthetic USD 5,000 + 150 = 5,150; separate seller basis/commission/net; immutable snapshots; strict bounded integer minor units; body/currency/subject/purpose/revision binding; concurrent identical create; idempotency field conflict; quote ownership; fresh Identity outage; persistence across new runtime; expiration just before/equal/after.

M01: authenticated service event receiver; service-purpose/audience/source guards; envelope and occurrence deduplication; canonical listing without implicit read; ownership of list/markers/cursor/destination; optimistic revision and idempotent mutation; required notices survive optional preferences; unavailable destinations do not grant access; event intent in the same transaction.

D03: concurrent owner-private draft create; immutable first idempotent outcome; scoped read/update; stale writes denied; restart persistence; independent upstream unavailable statuses; allowlisted reservation projection; server-enforced disabled payment/send/accept capabilities. A saved draft is never an accepted offer, and a reservation is never a paid order.

## Integration gate

The feature routes import canonical L01 `@/features/identity/session`. The frozen handoff types alone are not a production provider. Actual Orders reservation-read DTO/path and Auction notice destination projections must be checked against their owners' runtime before calling the connected demo complete. Physical-device install, keyboard and assistive-technology proof are distinct from desktop/phone browser emulation.
