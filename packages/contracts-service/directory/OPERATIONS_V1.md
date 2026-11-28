# Directory operations v1

Public reads: `GET /v1/directory/businesses`, `GET /v1/directory/businesses/{organization_id}`. Cursor pages include a server `total` of published profiles for the requested purpose, before current business verification. Each page verifies current eligibility; its visible length is never the total. Empty filtered pages may still have a next cursor. No customer evidence is public.

Private reads: `GET /v1/directory/choices/current` for the current subject; `GET /v1/directory/maintenance/{organization_id}` requires current selected-business `business.jobs.write`, including unpublished offerings.

Commands: `PUT /v1/directory/businesses/{organization_id}` requires current selected-business `business.jobs.write`; `POST /v1/directory/choices` requires a buyer and current published capability/profile revision. Both bind a stable `Idempotency-Key`, actor, business, body and expected revision. Same-key same-body retries return the retained result after current authority is checked. Changed bodies conflict. Stale/reordered revisions never overwrite newer facts. Command result and identifiers-only outbox event share one transaction.

A selection saves a destination only. It never confirms an appointment, allocates a watch, accepts a quote, receives custody, charges or authorizes work. Servicing and customization are separate purposes; only an active authorized brand may offer customization. Dealers may offer currently authorized servicing. Demonstration business capabilities are synthetic declarations, not real agreements.

Timeout or lost response is unresolved. Keep the original reference/body and retry. Denied authority requires current permission; stale revision requires explicit reload/review. Missing business facts remain unavailable. Publication is not a second source of business authority. Server-side authority is rechecked on every private read and command.

Lookup: `GET /v1/directory/operations/{operation_id}?command=choose` or `command=publish:{organization_id}` returns the stable operation envelope, with nullable retained `result`. Unknown references remain pending and do not prove non-execution. Buyer receipts require current buyer access. Publication receipts recheck current selected-business write scope and current business eligibility; possession of a reference grants no access.
