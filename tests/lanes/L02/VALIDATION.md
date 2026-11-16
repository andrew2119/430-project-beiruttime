# L02 verification record

## Passing proofs

- **45 lane API/database tests** use real PostgreSQL, the published Accounts RS256 guard, live session rows and recipient-bound password-proof consumption. No principal is mocked. Disposable databases use restricted runtime credentials.
- **68 full Docker tests pass** across the core runtime, transport and L02. The two ordinary-suite skips are the explicitly opt-in live-browser service and owning-runtime Compose proof; both have separate executed proofs. Actual Identity runtime-role checks also prove cross-database access and runtime DDL are denied.
- **The real owning Identity runtime passes a separate Compose proof**, using the merged Accounts runtime and read-only current-source mounts in the existing image: real registration, contact proof, operator onboarding, staff grants, private application, assigned review, revocation and actual process restart. No case or successful endpoint is substituted in this connected flow. The task's proof container is left stopped.
- **Production web build, 66 core web tests, five private-form restoration regressions and lane Ruff checks pass.** The unchanged strict feature web lint rules pass, including React ref safety. Feature TypeScript also passes against the frozen Accounts session contract; production imports the real session adapter rather than a local invented identity.
- **Eight connected public browser cells pass:** English/Arabic, light/dark, 1440×900 desktop and asserted 390×844/DPR 3 phone emulation. The directory reads real operator-created sample organizations. Checks include translated sample labels, RTL, actual theme colors, clipped content, touch targets and absence of any public business application form. Machine-readable evidence is in `evidence/public-desktop.json` and `evidence/public-phone.json`; the desktop image was visually inspected.

- **Forty connected private browser cells pass:** all five owned pages in both languages, themes and asserted desktop/390px widths. Real Accounts registration and sign-in screens establish the identity. The flow proves Arabic-digit contact verification with sample delivery labels, official brand onboarding, organization-only colleague grants and staff reads, actual applicant text uploads, assigned private evidence download, reasoned approval and applicant-visible history. No API or identity is intercepted. `evidence/private-interactions.json`, `private-desktop.json` and `private-phone.json` record the outcomes; both Arabic/dark screenshots were visually inspected.

The bounded browser runner starts the actual Accounts/L02 service against an isolated real database and the production web server, then shuts down every owned process. The public proof first passed with the browser CLI. Its fresh sessions later failed page selection, so the final forty-eight-cell rerun uses the authorized installed-Google-Chrome headless fallback through its native DevTools protocol (`headless-browser-proof.mjs`). No added browser dependency, mocked response, injected client identity or idle overnight test process remains. A further two phone-width outage cells stop the actual owned Identity fixture and verify EN/AR unavailable recovery, an enabled retry action, no editable private form and no false success (`evidence/private-outage.json`).

The private proof exposed a restoration race: an early membership entry could be erased by the acknowledged account boundary. Private forms now wait for session restoration to settle; public business discovery remains available during an Identity outage. Five web regressions cover authenticated/restoring/signed-out/unavailable and public admission.

## Covered behavior

Independent exact operator capabilities (business, membership and reviewer authority never imply one another); operator-only official onboarding; no third-party provider kind or public grant; default active business assurance; stale revisions; duplicate/concurrent operation receipts; exact organization-scoped staff capabilities; qualifications and intervention scope; capability ceilings; self-intervention denial; suspension/reactivation and business revocation; atomic grant/session fencing against a waiting stale command; verified-only private delivery projection; Arabic phone/code digits without mailbox substitution; expired/replayed codes and proofs; before/equal/after minute/hour/expiry boundaries; five wrong-code attempts; pending-recipient exclusion; durable sample-contact labels and schema upgrade; assigned independent review; complete/private evidence binding; atomic application/publication grant and revocation; current reviewer qualification; reassignment; private attachment and durable denial audit; bounded owner-private reason-history pagination; meaningful decision reasons; outbox rollback; acknowledged-state recovery.

## Reproduction

```sh
export PYTHONPATH="$PWD/packages/runtime/src:$PWD/packages/bulkheads/src:$PWD/packages/events/src:$PWD/packages/contracts-core/src"
TEST_DATABASE_ADMIN_URL=postgresql://…/postgres .venv/bin/python -m pytest tests/lanes/L02 -q
.venv/bin/ruff check services/identity/modules/{contacts,businesses,membership,private-review} tests/lanes/L02
pnpm build
pnpm test
pnpm --dir web exec vitest run --config features/business/vitest.config.ts

docker build --target test -f services/_template/runtime/Dockerfile -t beirut-time/l02-foundation-test:local .
docker build -f tests/lanes/L02/Dockerfile -t beirut-time/l02-module-test:local .
# Use the shared PostgreSQL network and maintenance URL; include TEST_RUNTIME_URL
# from the foundation Compose configuration for restricted-role boundary checks.
# Reuse existing images with read-only current-source mounts for later checks;
# leave completed proof containers stopped and never prune shared build storage.

TEST_DATABASE_ADMIN_URL=postgresql://…/postgres tests/lanes/L02/run-private-browser-proof.sh
BT_L02_COMPOSE_PROOF=1 TEST_DATABASE_ADMIN_URL=postgresql://…/postgres .venv/bin/python -m pytest tests/lanes/L02/test_runtime_compose.py -q
```

Published Accounts files in `fixtures/` are deterministic provider contracts used only when that provider source is not present. The production modules use the authorized same-domain `service_app.identity` transaction seam. Test bootstrap identities and evidence are synthetic and labeled; sample businesses are created through real operator APIs.

## Integration status

Foundation and Accounts are integrated from `origin/main` with normal merge history; their files are authoritative, not lane-owned copies. All temporary Accounts/web-registration copies have been replaced by main. The unrelated auction-management page on main imports the frozen Pricing quote type; its published DTO is used locally without being committed by this lane. All production feature changes and evidence stay within L02-owned paths.

State-change intents are durable in the shared Identity outbox. The Accounts-owned relay currently has a Communications destination; Catalog, Auction and Service Operations destinations require their owners' bounded receiver/client integrations. No external delivery or downstream grant propagation is claimed before those destinations acknowledge it.
