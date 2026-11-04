# L02 verification record

## Passing proofs

- **41 lane API/database tests** use real PostgreSQL, the published Accounts RS256 guard, live session rows and recipient-bound password-proof consumption. No principal is mocked. Disposable databases use restricted runtime credentials.
- **62 full Docker tests pass** across the core runtime, transport and L02. The one skip is the explicitly opt-in live-browser service. Actual Identity runtime-role checks also prove cross-database access and runtime DDL are denied.
- **Production web build, 48 web tests and lane Ruff checks pass.** Feature TypeScript also passes against the frozen Accounts session contract; production imports the real session adapter rather than a local invented identity.
- **Eight connected public browser cells pass:** English/Arabic, light/dark, 1440×900 desktop and asserted 390×844/DPR 3 phone emulation. The directory reads real operator-created sample organizations. Checks include translated sample labels, RTL, actual theme colors, clipped content, touch targets and absence of any public business application form. Machine-readable evidence is in `evidence/public-desktop.json` and `evidence/public-phone.json`; the desktop image was visually inspected.

The bounded browser runner starts the actual Accounts/L02 service against an isolated real database, starts the production web server, drives Chrome without API interception, then shuts down the fixture, web server and browser. No idle overnight test process remains.

## Covered behavior

Operator-only official onboarding; no third-party provider kind or public grant; default active business assurance; stale revisions; duplicate/concurrent operation receipts; exact organization-scoped staff capabilities; qualifications and intervention scope; capability ceilings; self-intervention denial; suspension/reactivation and business revocation; atomic grant/session fencing against a waiting stale command; verified-only private delivery projection; Arabic phone/code digits without mailbox substitution; expired/replayed codes and proofs; before/equal/after minute/hour/expiry boundaries; five wrong-code attempts; pending-recipient exclusion; durable sample-contact labels and schema upgrade; assigned independent review; complete/private evidence binding; atomic application/publication grant and revocation; current reviewer qualification; reassignment; private attachment and durable denial audit; bounded owner-private reason-history pagination; meaningful decision reasons; outbox rollback; acknowledged-state recovery.

## Reproduction

```sh
TEST_DATABASE_ADMIN_URL=postgresql://…/postgres .venv/bin/python -m pytest tests/lanes/L02 -q
.venv/bin/ruff check services/identity/modules/{contacts,businesses,membership,private-review} tests/lanes/L02
pnpm build
pnpm test

docker build --target test -f services/_template/runtime/Dockerfile -t beirut-time/l02-foundation-test:local .
docker build -f tests/lanes/L02/Dockerfile -t beirut-time/l02-module-test:local .
# Use the shared PostgreSQL network and maintenance URL; include TEST_RUNTIME_URL
# from the foundation Compose configuration for restricted-role boundary checks.

TEST_DATABASE_ADMIN_URL=postgresql://…/postgres tests/lanes/L02/run-browser-proof.sh
```

Published Accounts files in `fixtures/` are deterministic provider contracts used only when that provider source is not present. The production modules use the authorized same-domain `service_app.identity` transaction seam. Test bootstrap identities and evidence are synthetic and labeled; sample businesses are created through real operator APIs.

## Remaining delivery gates

The published L01 web registration, private-seller API source and complete runtime/Compose fragment are still needed for signed-in end-to-end browser and authoritative Compose acceptance. Public-origin and locale proxy fixes are copied locally from the foundation handoff, uncommitted. After the owner source lands, rerun the signed-in contact/onboarding/staff/private-review flows in both languages/themes and both widths, reconcile all copied files with main, and repeat checks. No signed-in browser or final demo completion is claimed by the public-directory proof.
