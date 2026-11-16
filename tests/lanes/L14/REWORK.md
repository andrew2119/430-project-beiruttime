# Revised offers and quote checks

## Implemented scope

- Full-step private bid state, inactive displaced ceilings, fixed scheduled ends,
  no new auction purchase and version-tagged retained public history.
- Registered additive migrations; USD-only active admission and no conversion of
  historical records.
- Fifteen-minute previews, forty-eight-hour sent offers, immutable sent terms,
  stable accepted revisions, own-block removal and bounded cross-route closure.
- Non-expiring accepted economics, unchanged accepted quote reuse, customer-only
  decisions, current assessment/business checks and separate execution authority.
- Watch fees remain 3%/5%. Jobs charge the customer only the accepted base, deduct
  5% from the business and retain the full-refund business-fee obligation.
  Assessment/return fees have explicit separate acceptance flags. Return transport
  is not silently added to the job base twice.
- Existing quote/offer screens use dollar input/display, both language copies,
  the same shared controls and in-memory state/operation references. No new shell,
  palette, navigation tree or browser persistence was introduced.

## Focused checks

Python unit checks (no database or service process):

```
python3 -m pytest -q tests/lanes/L14/unit -o addopts=''
```

They cover full-step examples/bands, inactive maxima, malformed result/privacy
boundaries, fixed deadlines/close refusal, exact cents/half-up fees, retained
accepted quotes, unchanged reissue, source/consent/authority denial, sent-offer
lifetime, late acceptance, own-unblock and migration registration.

Frontend unit and type checks:

```
pnpm --dir web exec vitest run --root "$PWD" --config tests/lanes/L14/vitest.config.ts
web/node_modules/.bin/tsc --noEmit -p tests/lanes/L14/tsconfig.json
```

Frontend units check exact dollars/Arabic digits, business-only deductions,
optional lines, unchanged command payloads/operation keys across translated copy,
matching bilingual keys, offer route admission and order navigation. These are
not browser interaction evidence. Changed Python and frontend source is also
linted; no broad suite or build is needed for these checks.

## Evidence still owed

- Run the complete merged migration set against restricted service databases,
  including upgrade from accepted bids/offers and historical non-USD records.
- Connect the private proxy v2 implementation and revised Orders allocation,
  notification-clock and attempt-aware recovery interfaces.
- Check actual assessment/request/identity providers and independent consent/
  eligibility/approval revocation. Pricing grants no execution authority and has
  no capacity scoring or substitute wealth attestation.
- Subscribe notice/quote destinations before enabling their relays. Reconcile
  actual Buy Now and confirmed withdrawal projections; unknown/missing results
  must remain pending, not close offers speculatively.
- Exercise real desktop/390px, both languages/themes, keyboard, in-place language
  switching and failure/recovery paths after the shared frontend is ready.
- Prove actual simulated payment, fee collection/receivable reconciliation,
  custody, receipt, completion and release with the owning domains. The pending
  readiness fixture is contract data, not evidence of any of those outcomes.

The older connected/browser scripts and database tests are not proof of revised
behavior until rerun against the revised providers. Their focused quote fixtures
were updated, but connected execution is deliberately deferred.
