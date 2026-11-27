# Brand decisions and read-only readiness

Commands and immutable request scope are in request-drafts/V2.md. Closed reference-only events remain v1 (`v1.py`). `v1.ts` defines exact ApprovalBindings and the discriminated DecisionReadiness response; the versioned publication is brand-decisions/v2. A retained approval is not payment, an execution grant or a job.

GET `/v2/customization-requests/{id}/decision-readiness` (additive browser v1 alias) first checks fresh actor/target-brand/current request permission. Available reads return `{status:available,bindings:ApprovalBindings,execution_authority:false}`. A bounded prerequisite-service outage returns HTTP 200 `{status:unavailable,code:approval_unavailable,execution_authority:false}` with **no bindings**. This optional read must not open a healthy Catalog circuit and prevent unrelated listing/request reads. Wrong permissions still deny; expired/stale/mismatched facts do not become available.

Clients must branch on status, discard failed/in-flight rechecks and never treat a truthy unavailable object as authority. Decision POST remains a separate current-scope guard: it persists intent before HTTP, returns unavailable/pending on uncertain authority results, and confirms only after exact serialized acknowledgement. No read creates a decision, consumes a grant, authorizes work or copies private eligibility evidence into Catalog.
