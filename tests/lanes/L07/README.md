# L07 verification

## Commands

- `BT_TEST_LANE=L07 python3 scripts/test-services.py pricing communications`: isolated PostgreSQL databases/roles; Docker domain and foundation proofs.
- `./infra/foundation/dev.sh pricing communications`: build real production images, apply module-local migrations, start the two runtime owners. Preserve shared PostgreSQL; stop only these two containers after a local run.
- `pnpm --filter beirut-time-web exec tsc --noEmit -p ../tests/lanes/L07/tsconfig.json`: compile the L07 screens against the frozen Identity session type fixture while L01 has not been integrated.
- `pnpm --filter beirut-time-web exec vitest run --config "$PWD/tests/lanes/L07/vitest.config.ts" --root "$PWD"`: exact localized money parsing/display.
- After L01 integration: full web typecheck/build/lint/unit tests and `bash tests/lanes/L07/browser-matrix.sh` against a local real app. It uses the named `bt-l07` Chrome session, requires prior real Account sign-in and records 24 route/locale/theme/width geometry observations and screenshots under ignored `.runtime/`.

No fixture grants authority or fabricates a successful transaction. HTTPX transports in service tests model independently versioned dependencies, and are never enabled by the application. The production application must be tested with the real Identity, Pricing, Communications and Orders APIs before final acceptance.

## Coverage

Q01: synthetic USD 5,000 + 150 = 5,150; separate seller basis/commission/net; immutable snapshots; strict bounded integer minor units; body/currency/subject/purpose/revision binding; concurrent identical create; idempotency field conflict; quote ownership; fresh Identity outage; persistence across new runtime; expiration just before/equal/after.

M01: authenticated service event receiver; service-purpose/audience/source guards; envelope and occurrence deduplication; canonical listing without implicit read; ownership of list/markers/cursor/destination; optimistic revision and idempotent mutation; required notices survive optional preferences; unavailable destinations do not grant access; event intent in the same transaction.

D03: concurrent owner-private draft create; immutable first idempotent outcome; scoped read/update; stale writes denied; restart persistence; independent upstream unavailable statuses; allowlisted reservation projection; server-enforced disabled payment/send/accept capabilities. A saved draft is never an accepted offer, and a reservation is never a paid order.

## Integration gate

The feature routes import canonical L01 `@/features/identity/session`. The frozen handoff types alone are not a production provider. Actual Orders reservation-read DTO/path and Auction notice destination projections must be checked against their owners' runtime before calling the connected demo complete. Physical-device install, keyboard and assistive-technology proof are distinct from desktop/phone browser emulation.
