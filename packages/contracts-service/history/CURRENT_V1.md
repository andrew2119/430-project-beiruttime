# History v1

Read `GET /v1/history/{watch_id}?operation_id=…&expected_revision=…&page=0&page_size=20`.
Lookup `GET /v1/history/operations/{operation_id}` rechecks current scope and reruns the original read. These additive adapters require runtime composition before use.

The authenticated current context supplies actor, subject, selected organization, watch scope, assignment and revision. Request identifiers never establish permission. Providers recheck all of them on every read and lookup. Calls have a two-second bound, one attempt, at most 50 entries and authoritative server totals. A timeout returns unavailable; repeat the same operation reference. Reads have no financial, custody, entitlement or release authority.

Only actual work under a released completed job is eligible. Pending, rework and unrepaired return records are excluded. The current source revision must cover all late events before a page can be ready. A newer rework fact invalidates an earlier completion assertion. Warranty issuer, scope, UTC start and exact bilingual terms revision come from immutable reviewed source facts, never the current business profile. Aftercare uses the original job reference and grants no entitlement.

Source adapters must provide structured approved work codes and reviewed warranty terms containing no identity or evidence. Arbitrary notes, names, serials, evidence and file references are never accepted as display fields. Resale uses only an explicit currently authorized owner publication selection from these same safe fields. Publication cannot enlarge private scope. No former-owner data is published.

Result states are ready, pending, denied, stale and unavailable. Empty is a ready result with total zero. Every non-ready response has zero entries. Operation references bind actor, subject, watch, business, expected source revision and pagination. A conflicting duplicate is denied. Durable provider operation storage is required before exposing lookup across restart; no local process cache is authoritative.

## Owner publication v1

`POST /v1/history/{watch_id}/publication` accepts `PublicationBody`: stable operation UUID, expected source revision and at most 50 distinct job UUIDs. The current context supplies actor, subject and selected business. The result is `PublicationResult`, with the same bound envelope as reads and schema version `history-publication.v1`. Empty selection withdraws the whole public subset. No supplied text, evidence, warranty replacement or scope expansion is accepted.

`GET /v1/history/publication/operations/{operation_id}` looks up the durable original receipt under current owner, subject and selected-organization permission. A lost response is pending; repeat the original POST or look up its exact reference, including after restart. A lookup without a durable receipt is not evidence of failure or permission to change the request.

The provider must serialize `commit_publication` with source ownership/revision and released-work mutations. It rechecks each selected job remains actual, completed, quality-passed and released; atomically replaces only safe entry snapshots and stores the fully bound versioned receipt. Identical duplicates return that receipt; conflicting duplicates deny. `safe_released_job` returns only the reviewed Entry shape, never raw source fields. `current_owner` checks current actor, subject, watch and selected business scope, including lookup after ownership changes. These methods and durable storage require the connected provider; synthetic fixtures exercise the boundary without claiming that connection.
