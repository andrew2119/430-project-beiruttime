# Current request submission contract

A seller-base reference records purchase intent only. Saving, validation and formal submission never reserve, allocate or purchase a watch. A later linked job requires a completed protected purchase and a separate accepted quote and payment. A reservation or unpaid order is insufficient.

Submission freezes exactly five current option snapshots, base, caliber, attached dial references and private draft content. Missing or stale dimensions return `details.fields` without changing the draft. Manual assessment permits review submission but never implies feasibility or execution authority.

Commands require a stable `Idempotency-Key`, personal buyer scope and exact source revisions. Repeating identical bytes returns the retained request reference even after response loss; changed bytes conflict. Identity is checked on every retry. Brand activity is checked before new submission. Private operation reads belong to the originating buyer or currently scoped target business.

`GET /v1/request-drafts?limit=50&before={id}` returns `{items,total,next_cursor}`. Limit is 1–100. Ordering is descending update time and identifier. Cursors must belong to the current buyer. Totals come from the same database snapshot as rows.

`GET /v2/customization-requests/{id}/revisions?limit=50&before_revision={revision}` returns `{items,current_revision,total,next_cursor}` in descending revision order. Revision numbers are contiguous from one; the current revision is the total. Each revision includes its original reason, actor and creation time. A correction appends; it never replaces earlier content.

`GET /v2/customization-operations/{operation_id}` reads a durable result. When a response is lost before its identifier is known, retry the original command with its original key and body. An unavailable dependency remains uncertain; do not generate a replacement operation.

Language navigation changes presentation in place and never invokes a command. Private notes, file bytes and pending operations remain in mounted memory only. Access changes clear private memory and reject late answers.
