# Offer recovery v2

Operations use a stable Idempotency-Key and current party authorization, including
replayed block removal. Removal deletes only the calling party's block.

Operation lookup: acceptance uses Orders `GET /internal/v2/operations/{operation_key}`.
Missing means retry the retained `POST /internal/v2/allocations` command with the
same key. Timeout, malformed success, mismatched order bindings and pending results
remain acceptance_pending. No charge or reservation is inferred locally.
A succeeded order must bind watch_id, listing_id, buyer_id, quote_id, quote_revision, currency and
total_minor to the retained command. The order identifier must be a UUID string;
quote_revision and total_minor must be integers, excluding booleans. Offer revision increments only on transition.

A confirmed reserved or withdrawn physical watch closes every open offer for that
watch, including other listing references. Catalog withdrawal closes only its own
listing. Missing or uncertain facts do not close offers. Closure updates and each
recipient notice share one transaction; repeated delivery cannot close twice.
Concurrent reconciliation returns the current stored state, including pending.

Connected Orders v3 retained-economics and payment-notice proof remains required.
