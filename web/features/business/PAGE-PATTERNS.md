# Business and operations page patterns

All pages use the shared Calm card `PageHeader`, Pane tabs and list-page/tray spacing. Typography comes from the shared sans family, including Arabic.

## Page compositions

- `/business`: Calm header with route tabs, `pg-card` business rows, status chips and quiet references. The operator onboarding panel uses section-card/form-field spacing and native submission. Capability choices use Checkbox; loading uses row skeletons; empty and failed loads use State.
- `/business/contacts`: Two current-contact panels above a contact-change form with shared Input, Select, Button and status chip. Pending proof stays in the same section behind a hairline. Password, proof expiry, simulated-code reveal and six-digit verification remain unchanged.
- `/business/membership`: Compact lookup toolbar and member cards with revision metadata, status chip and editable form. Grant/edit forms use shared Input, Select and Checkbox with common focus, press and disabled states.
- `/business/review-history`: Calm header and empty/failed faces. Review cards use the `pap-timeline` / `pap-step` decision timeline, status chips and existing older/latest pagination.
- `/operations/verification`: Queue beside a decision panel. Rows keep fixed reference/state/action slots; facts, downloads, verdict and history use `pap-panel` blocks. Assignment uses form cards. Selection has a pressed state and shared motion. Phone layout stacks queue and panel.
- `/business-intake`: Organization Select and intake queue beside an editor card. Identity, condition, permissions, fees and currency use shared controls. Evidence uses common list-row/upload controls. Phone layout stacks the queue/editor, retaining native validation, custody guards, idempotency and file restrictions.
- `/operations/moderation`: Queue and decision panel with shared report/reference controls. Explicit selection, claim and release actions remain. Evidence and policy use soft surfaces, not colored edge stripes. Decision/appeal forms retain independent pending/error states and revision guards; audit events use the timeline.
- `/operations/dashboard`: Queue cards with quiet metadata, status chips and button links. Actual queue items and prerequisite/denied/unavailable states remain the source of truth; no invented metrics.
- `/operations/dashboard/queues/[key]`: The same overview/queue composition for one queue, retaining its route and endpoint.

## Shared states and motion

Boundaries preserve authentication restoration, access-fingerprint remounting and retry behavior. State, RowSkeleton, AnimatedList and the shared content-entry recipe own empty/error/loading and list motion. Buttons and fields inherit focus, hover, press and disabled states from `@beirut-time/ui`. Tabs are real locale-aware links with an active route.

EN/AR copy and bidi isolation remain intact. Feature CSS only supplies token-consuming layout with logical properties; it defines no palette, font, radius, shadow or keyframe system.

See [the design contract](../../../docs/design-system.md) and [validation](VALIDATION.md).
