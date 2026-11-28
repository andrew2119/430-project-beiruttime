# Movement operations v1

`GET /v1/options/movement?brand_id=...&after=...` returns bounded cursor pages and the server total of active USD options. `GET /v1/options/movement/{id}` returns one active USD option. Both verify current brand customization capability.

`PUT /v1/options/movement/{id}` requires selected-business `business.stock.write`, current official brand customization capability, expected revision and stable `Idempotency-Key`. Ownership cannot transfer through an update. `POST /v1/options/movement/selections` binds current buyer, brand, exact option revision, expected selection revision and identified case/dial/hands/functions. `GET /v1/options/movement/selections/current?brand_id=...` returns only that subject's saved snapshot. A historic non-USD snapshot remains unchanged in restricted storage and is excluded from active forms with `archived:true`.

Amounts are integer USD cents; users enter and see dollars. A declared indicative reference is never a retained quote or authority to charge. Compatibility requires one exact declared combination. No rule, ambiguous rules or unsupported requirements means `manual_review`. Other results are `supported_for_review`, `incompatible` or `parts_unavailable`. Even a supported rule never approves physical feasibility, submits a request, reserves a base or authorizes work.

Every command rechecks current authority before same-reference replay. Exact replay returns the retained result; conflicting reuse and stale/reordered revisions deny. Lost response remains unresolved with the same operation reference/body. Storage and identifiers-only event publication are atomic. Database restart and connected producer proof remain separate from deterministic contract examples.

Lookup: `GET /v1/options/movement/operations/{operation_id}?command=select` or `command=publish:{option_id}` returns the versioned envelope and nullable retained result. Unknown references stay pending. Publication receipts require current selected-brand stock permission and current customization eligibility; buyer receipts require current buyer access. `GET /v1/options/movement/maintenance/{brand_id}` lists current USD offerings, including withdrawn options, for currently authorized stock staff. Republishing uses the retained option revision and explicit activation.

Legacy non-USD offerings cannot be edited or converted under their existing identifier. Publish a separate USD offering. Current-selection reads expose `selection_revision` even when `archived:true` hides the historic amount. Explicit replacement binds that revision and atomically preserves the original snapshot in restricted archive storage before saving the USD selection.

Operation lookup marks historic non-USD receipts with `archived:true` and `result:null`; only revision metadata remains active. Retained receipt bytes remain unchanged.

Identical selection retries for historic non-USD receipts return `archived_currency` without an amount. The stored receipt remains unchanged; current-selection revision metadata supports explicit replacement with a current USD option.
