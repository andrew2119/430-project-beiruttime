# Auction admission and bidder notice verification

## Commands

```sh
export PATH=/Users/andrew/.harness/homes/430-project/firstmate/data/bt-tools/bin:$PATH
python3 tests/lanes/L05/verify.py
web/node_modules/.bin/vitest run --config web/features/auction-management/vitest.config.ts
web/node_modules/.bin/tsc -p tests/lanes/L05/web/tsconfig.json --noEmit
(cd web && node_modules/.bin/eslint features/auction-management registrations/L05.ts 'app/(auction-management)/seller/auctions/page.tsx')
```

The backend runner reuses the last local test images and bind-mounts current source read-only, creates restricted disposable PostgreSQL databases and cleans those databases/roles up. For an initial dependency build only, pass `--fresh`; for an existing image pair, pass `--auction-image <tag> --notices-image <tag>` once. Source-only changes never need another image build. Finished proof containers remain stopped; shared images, volumes and cache are never pruned here. It leaves the shared PostgreSQL instance alone. Auction tests exercise actual FastAPI commands, SQL constraints, stored operation acknowledgements and durable outbox intent. Communications tests exercise service-token ingress, transactional inbox/deduplication, private reads, canonical reread and leased Inbox bridge retries. Upstream transport fixtures are explicit test doubles, not production fallbacks or database seeds.

The isolated TypeScript check uses a contract-only Identity module alias under this test directory while the real provider is not merged. Production imports `@/features/identity/session` and never this test fixture. Full production build passes against the authorized uncommitted Identity provider snapshot and foundation patches. Signed-in connected browser acceptance still requires the real owning-service registrations and APIs; the isolated check is not a replacement.

The published L06 proxy module is copied uncommitted into its owning subtree for integration. SQL/API proofs also carry its frozen pure calculation as an explicit test fixture, exercise the actual discovered maximum route with a signed access token, and prove compatibility with manual bids accepted before the proxy module arrives. The test-only Communications image includes a separate Auction module tree solely to host two independently migrated, restricted databases for the HTTP outbox-to-notice proof. Production domain images remain separate.

## Current proof coverage

- One auction per listing/watch; exact integer currency validation; UTC window boundaries before/equal/after start and end.
- Stored accepted/denied operation replay, conflict on key reuse, owner-private reconciliation, acknowledgement surviving application reconstruction.
- Equal-price concurrent bid race, minimum increment, self/business-scope denial, stale revision, hidden listing, unknown sale fence, required current high-value contact and fee binding.
- Economic settings frozen in both API and PostgreSQL after first bid; monotonic accepted sequence/revision.
- One pure proxy hook inside the sole Auction transaction; actual L06 first/maximum/manual/equal-cap/partial-cap/leading-raise behavior; malformed proxy writes refused; no private maximum in public projections or authenticated bid events.
- Canonical Identity listing-publish permission and exact current organization re-selection; no cross-business permission mixing or business-member personal self-bids. Orders service-token fencing and source-bound reconciliation after a lost remote response.
- Authenticated service-purpose event ingress, exact event schema, one required outbid notice per recipient/event, unchanged-leader suppression, current-state reread for historical notices and honest unavailable recovery.
- Actual SQL outbox delivery over authenticated HTTP into a second domain database, owner-private outbid retrieval, canonical Auction reread, event replay deduplication and destination lease isolation.
- Durable retry of Inbox delivery independent of optional channel preferences (the final L07 writer contract remains to be integrated).
- EN/AR money normalization, safe uncertain reconciliation, no optimistic acknowledgement, cancellation and complete bilingual dictionary keys.

## Connected browser checklist

Use an isolated `CHROME_DEVTOOLS_AXI_SESSION=bt-l05` and a lane-local web port. Test 1280×900 and 390×844 in EN/AR and light/dark. Use real signed-in seller and buyer sessions, an actual published sample listing and a confirmed Orders auction commitment. Create the auction through the seller form, review server rules, obtain exact fee previews, and submit real bids from two buyer sessions. Check the prior buyer's canonical inbox and current-state reread. Repeat low/self/late denials, lost-response reconciliation and account switch without stale private state. Capture browser/geometry results here only after running them. Stop the lane browser and containers when finished.

## Recorded pre-authentication browser proof

After applying both foundation locale-proxy files, production GET/HEAD `/en/seller/auctions` and `/ar/seller/auctions` return 200 without redirects. The signed-out seller boundary was exercised through chrome-devtools-axi at 1280×900 and explicit 390×844×3 mobile/touch emulation in both locales and both themes: correct language/direction/theme, no horizontal overflow, in-bounds 44px theme/sign-in targets and keyboard-reachable skip control. This is NOT the signed-in Auction demo or a substitute for live fee/bid/Inbox integration.

`node tests/lanes/L05/capture.mjs http://localhost:3105` records the same eight screenshots and geometry checks under ignored `tests/lanes/L05/artifacts/screens/`. It uses explicit headless device metrics because this Mac's plain window-size screenshot could paint a wider layout into a narrow PNG. Screenshots and JSON are local evidence, not application data or CI.

`python3 tests/lanes/L05/check_owned_paths.py` checks the staged and committed diff against the exact lane ownership set; authorized untracked provider/foundation handoffs are deliberately not treated as committed changes.

The copied Identity provider currently allowlists `/seller/verification` but not `/seller/auctions`, so its sign-in return link falls back to `/account`; this owning-provider integration correction is pending, not hidden by a local provider edit.

No paid order, closed winner, inspection pass, payout or winning bid is seeded by this lane.
