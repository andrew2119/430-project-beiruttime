# Exclusive reservations and private request drafts

## Local verification

- Start only this runtime with `./infra/foundation/dev.sh orders`. The launcher preserves shared PostgreSQL. Stop only the Orders container started for this check afterward.
- `python3 tests/lanes/L08/test-modules.py` reuses one checkout-local dependency image and mounts the current owned modules, tests, shared Python source and freshly packaged contracts. It rebuilds only when dependency manifests change or `--build-dependencies` is explicit. An existing validated image can bootstrap the cache with `--reuse-image <local-L08-tag>`. Finished proof containers remain stopped; no shared image, volume or cache is pruned. Orders and Request Drafts run separately against unique restricted-role PostgreSQL databases; only the owned Catalog module is loaded, never another authoritative Catalog runtime.
- `web/node_modules/.bin/vitest run --config tests/lanes/L08/web/vitest.config.ts` checks locale parity, signed-out boundaries, no public internal mutation, and memory-only owner partitioning.
- `python3 -m unittest discover -s tests/integration/sprint-1 -p 'test_*.py'` checks the evidence runner itself. These are **runner tests**, not full marketplace acceptance.
- Before Identity's implementation lands, `BT_IDENTITY_CONTRACT_FIXTURE=<read-only-session-contract-directory> node tests/lanes/L08/check-web-contracts.mjs` checks against its frozen type-only consumer interface. There is no runtime success fallback. Final checks use the real integrated module and ordinary `pnpm typecheck` / `pnpm build`.

## Authenticated browser proof

`python3 tests/lanes/L08/live-proofs.py start` reuses existing local images for a real Identity loopback replica and a restricted, isolated draft database. It does not replace the authoritative Catalog or restart shared Identity. Its ignored state file contains loopback URLs only, never credentials. It requires the actual published Identity frontend/registration to be present as consumer input. Build the current frontend, set its `IDENTITY_API_URL` and `CATALOG_API_URL` from that state, and publish only the two exact `web_origins` as `BT_PUBLIC_WEB_ORIGINS`, with `BT_TRUST_FORWARDED_ORIGIN=false`. Run that production frontend on loopback port 3108.

In a fresh named `chrome-devtools-axi` session opened on that origin:

1. Emulate `1280x900x1` and run `chrome-devtools-axi run < tests/lanes/L08/browser-save.js`. This uses the actual sign-in form, actual save and acknowledged dirty locale navigation. It emits only the opaque draft reference and safe booleans.
2. Run `browser-matrix.js`, emulate `390x844x3,mobile,touch`, and run it again. The script refuses an unexpected viewport and checks the rendered theme, RTL, durable notes, keyboard focus, target sizes and overflow.
3. Run `browser-privacy.js` for six actual unreleased-command denials and logout/second-profile non-disclosure. Credentials remain inside short-lived browser request closures.
4. Stop the named browser, the owned frontend listener and `python3 tests/lanes/L08/live-proofs.py stop`. Finished containers/images are retained. This isolated proof explicitly does **not** accept full E05.

See `validation.md` for the last verified boundaries and remaining connected gate.

## Publication boundary

`python3 tests/lanes/L08/foundation-bytecheck.py <read-only-foundation-snapshot>` checks every copied foundation file against `origin/main` without deleting anything. Optional `--extra <relative-provider-file>` checks byte-identical provider fixtures once their owner merges. Remove only verified identical untracked copies, merge the owning reference normally, and rerun checks. Never include these temporary foreign files in a feature commit.

`python3 tests/lanes/L08/validate-scope.py --staged` checks a prepared logical commit; without `--staged` it checks the complete feature diff against merged `origin/main`. Neither command stages, commits, publishes or changes repository state.

## Demo on the integrated application

1. Use real authorized publication to register an actual sample listing's immutable physical-watch id in Orders. Obtain a current exact Pricing quote for each of two signed-in buyers.
2. Race `POST /v1/reservations` with two different buyer identities and stable operation keys. Exactly one obtains an awaiting-payment reservation. The other receives a durable denied outcome and no payment authority. Retry both keys: the original outcomes return unchanged. Reopen the winner after runtime restart.
3. Confirm self-purchase, stale revision, mismatched/expired quote, unauthorized organization, duplicate listing identity and unknown dependency cannot allocate a second watch.
4. Check the order state/history in `/checkout/{id}`. Paid, released, completed and cancelled transitions deny in Sprint 1. Expiry and unknown financial result both retain the physical fence; they never silently authorize another charge. Scoped intake staff may record actual pre-release physical facts, never final handover.
5. Open `/custom-requests`, select a real onboarded business and save neutral watch/scope intent. Reopen from the private server list, change language, and resume the same profile's neutral intent. A full locale navigation first acknowledges dirty private intent through the real draft API; only the opaque draft reference enters the URL, never notes or credentials. An unavailable save keeps the form open with the same operation key rather than losing it. Another profile sees neither the draft nor private custody facts. Current options and technical intake come only from bounded provider reads. Missing providers remain unavailable. Submission/payment/work/quality/collection never fake progression.
6. Exercise English and Arabic, light and dark, at desktop and 390px width with `chrome-devtools-axi` in a task-specific session. Use the real foundation shell and stop the browser session afterward. Do not substitute a screenshot or fixture response for a confirmed private save or reservation.

## Contract boundaries

Provider contracts live in `packages/contracts-orders/allocation/` and `packages/contracts-catalog/request-drafts/`. Runtime HTTP fixtures exist only inside the lane tests. Neutral draft intent is not compatibility, approval, formal quote, reservation or accepted work. All business writes, audit facts, operation digests and minimal outbox intent commit atomically in the owning database. No cross-service SQL or imports are used.

The complete connected slice remains separately gated by `tests/integration/sprint-1/`. Incomplete reports retain `complete: false`; unmerged providers are not marked accepted merely because the consumer module tests pass.
