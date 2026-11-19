# Saved searches v1

Personal buyer scope only: current identity, no represented organization. Every read, command, receipt lookup and notice opening rechecks that scope. Wrong owners receive the same missing response as absent records. Names and criteria are private and excluded from events and logs. No evidence, contact details or arbitrary destination URLs are accepted.

| Operation | Method and path |
| --- | --- |
| List searches | GET /v1/saved-searches?offset=0&limit=20 |
| Save, replace, opt in/out or remove | POST /v1/saved-searches/commands |
| Recover an uncertain command | GET /v1/saved-searches/operations/{operation_id} |
| List personal match notices | GET /v1/saved-searches/notices?offset=0&limit=20 |
| Read or clear a notice separately | POST /v1/saved-searches/notices/{id}/{read\|clear} with expected_revision |
| Open a notice with current public visibility | GET /v1/saved-searches/notices/{id}/destination |
| Receive publication | POST /internal/v1/saved-searches/events |

`Command` is immutable for an operation reference. Same owner/reference/body returns the original durable receipt; a different body returns 409 operation_conflict. Save creates at revision zero, replaces at the exact current revision, and cannot restore a removed identifier. Removal is a tombstone. At most 100 searches per buyer, 20 per list page. No result count is a save prerequisite. Notifications require explicit opt-in. Stored amounts are integer USD cents; forms accept exact dollars.

Pending means no acknowledgement was received: retain the exact reference and body, look it up or retry it. 404 lookup is not proof that a concurrent request cannot finish. 409 stale_revision requires current read and explicit review before a new operation. 401/403 deny, 503 unavailable and timeouts never imply success. Validation errors use invalid_filters or invalid_range as search does. The presentation translates these codes in place.

## Canonical provider boundary

Composition supplies `saved_search_catalog` with asynchronous `validate(criteria) -> Validation`, `match(publication, criteria, semantics_revision) -> Match`, and `visible(listing_id, source_revision) -> bool`. Calls have a 600 ms limit. Matching runs in batches of at most ten concurrent calls, with at most ten batches for 100 subscriptions. The delivery transaction has an eight-second deadline including storage; any timeout rolls back notices and receipt for the same occurrence to retry. Validation returns unchanged criteria and a retained canonical semantics revision. Matching must use Catalog's actual publication facts and canonical aliases, normalization, ranges and sale modes at that revision. It must bind every publication identifier and revision. This module never duplicates matching semantics or reads another service's tables. Missing or malformed provider data is unavailable. No local fixture is a runtime fallback.

The authenticated Catalog event is `catalog.listing-published.v1`, subject listing_id, with Publication as data and envelope time equal to published_at. Process at most 100 subscriptions for one explicit recipient per delivery; the producer supplies `recipient_id` in data. This recipient targeting must be produced by a bounded canonical subscription index before connected acceptance. No event may broadcast to every buyer. One occurrence per listing publication and one notice per subscription/occurrence; conflicting replay denies. Occurrences strictly earlier than the save or alert re-enable instant do not notify. Equality is eligible. Changes to criteria reset that instant. Delivery and receipt are atomic. A failed match rolls back the entire bounded delivery for stable retry. No mail/device delivery is claimed.

Composition and the canonical subscription index remain integration responsibilities. The module supplies its personal inbox for this category because the existing shared inbox category contract does not yet admit new-match notices. The required shared inbox adapter remains owed before connected acceptance.

## Page admission dependency

The proposed customer route is `/saved-searches`, with reusable view `web/features/saved-searches/view.tsx`. The executable page entry and navigation are withheld until shared admission is supplied. The localized shared loading boundary is supplied. Shared page-delivery admission must select the canonical shell with its root page-read provider before connected use. The additive registration is not active composition. The route must not join frozen migration debt. The current `web/lib/page-speed/pages.json` schema admits only internal routes and internal views; adding this customer route requires the owner to extend that schema and its rejection tests as well as register the entry and view. The existing internal demonstration read policy must not be assigned to these private reads. These shared changes are outside this module's ownership.

The requested admission has the following source contracts; none is a measured delivery verdict:

| Method | Current contract and remaining proof |
| --- | --- |
| Ready before press | No route admission or full destination payload warming is present. Admission, approved shell composition and a no-request-at-press measurement remain required. |
| Data on intent | Both reads intentionally use `warm: 'open-only'`; no private read occurs on intent. Any future warming needs an explicit safe-read decision by the shared owner. |
| Retained answers | Shared memory cache only, partitioned by current access scope. Search keys are `['saved-searches', fingerprint, 'searches', offset]`; notice keys substitute `'notices'`. Each request uses limit 20 and returns server totals. Identity/access changes invalidate the shared scope. |
| Content during refresh | The exact cached answer remains visible during refresh, with freshness zero. A different page key uses its own answer; no previous-page placeholder is requested. |
| First frame | The reusable view supplies row skeletons while no answer exists. The owned route loading boundary uses the shared PageLoading shape. No private answer is embedded in an initial document. Cold-load geometry and both themes remain unmeasured. |
| Arrival | The shared arrival component is keyed by selected tab. Interruption, reduced motion and revisit behavior require visual measurement. |

Page-size gates, bilingual desktop and actual 390-pixel viewport checks, keyboard flow, first-frame measurements and physical-phone review remain release prerequisites. Registration alone does not establish any of those results.
