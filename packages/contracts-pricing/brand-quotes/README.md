# Brand quote contract v1

Issue and decision routes retain the assessed wire shape in `../quotes/assessed.py`.
The brand-specific issue schema in `models.py` requires a positive amount and all
assessed lines to be mandatory. Amounts are integer USD cents. Customer total is
parts plus labor plus explicitly accepted assessment charges. The business alone
owes 5%, rounded half up; fee aliases describe one deduction. Return transport is
a separate conditional accepted line, excluded from the job total.

## Operations

- `GET /v1/brand-quotes/context` resolves current source and assessment revisions.
- `POST /v1/brand-quotes` issues the complete assessed configuration.
- `GET /v1/brand-quotes?page=1&page_size=10` returns items, unavailable, total, page and page_size.
  Stale records expose an opaque quote reference and recovery code, with revision
  and terms digest for personal buyer support; they do
  not hide a renewed quote on the same page or disclose its old private scope.
  Page size is bounded to 50; ordering is creation time then identifier descending.
- `GET /v1/brand-quotes/{quote_id}` reads a currently accessible quote.
- `POST /v1/brand-quotes/{quote_id}/accept` accepts exact revision, terms digest,
  complete line selection, total and separately acknowledged fee lines.
- `POST /v1/brand-quotes/{quote_id}/decline` records the customer's decision.

Commands require an Idempotency-Key. Lookup of a lost result is an identical retry
of the original command with that key, actor, selected business and body. The
receipt and decision share the existing transaction and outbox. Changing the body
or represented business conflicts rather than replacing the result. Current
identity and source authority are checked before a retained result is disclosed.
A timeout means unavailable: retry the same reference, never infer acceptance.

Only the personal buyer can decide. Business record reads require current scoped
permission. Source buyer, official brand, feasible assessment and exact revisions
must still match. Missing or malformed source facts fail closed. Issued previews
expire at equality, at most fifteen minutes after issue. Identical unchanged
accepted terms reuse the original quote after that deadline. Changed scope needs
a new quote and explicit acceptance; retained history is never repriced.

Current validation uses `../quotes/CURRENT_V3.md`; retained economics grant no
execution or payment authority. Consent, eligibility, allocation and payment
remain independent prerequisites. Source reads and record-access reads each have a four-second bound; issuance
rechecks both under its lock. A list has a five-second aggregate bound and never
returns partial success.

Fixtures are synthetic contract examples, not payment or completion evidence.

## Provider freeze

`fixtures/providers.v1.json` specifies the current request, assessment and business
read shapes consumed by this module. The proposed assessment read attests a
qualified assessor, current assignment and positive assignment/capability versions.
It binds the same physical watch and immutable request revision. Issued quotes
retain the watch, assessor and those versions. A missing qualification fact never
becomes permission through a fixture or an old projection. The provider must
supply this exact freeze before connected acceptance.

The three command schemas are published beside `models.py`. Deterministic
operation cases are in `fixtures/operations.v1.json`; provider examples contain
only synthetic scope and no private evidence references.

Business callers also require a current record-access response from
`GET /internal/v1/customization-requests/{request_id}/access?actor_id=...&organization_id=...&expected_revision=...`.
The response binds actor_id, organization_id, request_id and integer request_revision,
with allowed and assignment_current both true. Missing or mismatched bindings are
unavailable; a denied or removed assignment refuses issue, retry and private reads.
This provider contract requires connected verification before acceptance.
Accepted terms cannot be replaced by price, warranty or fee edits on the same
request and assessment revision. A revised assessed scope requires renewed acceptance.

`POST /v1/brand-quotes/{quote_id}/support` uses the decline command binding
(quote_revision and terms_digest), without making a quote decision or consenting
to fees. It requires the personal buyer and an Idempotency-Key. The atomic receipt
returns status pending, a receipt UUID operation_id, the stable action_reference
and next_actor support, and publishes
`pricing.brand-quote.support-requested.v1` to `brand-quote-support-v1` with only
quote/revision, buyer, organization and operation references. Identical retries
publish once. The page uses a deterministic quote/revision support reference, so
remounting recovers the same request. Current personal buyer access is rechecked before replay. Commercial scope,
consent and business authority are not support prerequisites. Unavailable list
entries for the personal buyer include only the quote reference, revision and
terms digest needed to request support; no stale commercial details are returned. No evidence or free text
is included. Recording is not delivery or a completed response. The support
consumer, operator assignment and response deadlines require connected proof.
