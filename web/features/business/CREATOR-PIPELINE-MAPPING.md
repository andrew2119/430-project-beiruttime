# Creator Pipeline port: business and operations

Reference frontend (read-only): `creator-pipeline-middleware/frontend`.
The current shared header is **A / Calm card**, not the older Marketing workspace header. All pages adopt its `PageHeader` and the shared list-page/tray spacing. The typography is the shared sans family (including Arabic); the previous serif business heading is removed.

## Page-by-page pattern mapping

- `/business`: Creator Pipeline Campaigns / Creators list page. Calm header with route tabs, `pg-card` business rows/cards, status chips and quiet record references. The operator onboarding panel adopts Settings section-card / form-field spacing and native form submission semantics. Capability choices use the shared Checkbox. Loading uses flat row skeletons; empty and failed loads use CalmFace, not prose floating in the page.
- `/business/contacts`: Creator Pipeline Settings Account section. Two current-contact panels above the contact-change form; shared Input, Select, Button, and status chip. Pending proof stays in the same section with a hairline and Settings-style status feedback. Password, proof expiry, simulated code reveal, and six-digit verification behavior remain unchanged.
- `/business/membership`: Creator Pipeline Admin People / Settings section cards. The lookup is a compact toolbar form; each member is a card with quiet revision metadata, status chip, and editable form. Grant and edit forms use shared Input / Select / Checkbox and the same control sizing, focus rings, press and disabled states.
- `/business/review-history`: Creator Pipeline Submissions history. Calm header and calm empty / failed faces. Reviews are cards, with the Approvals timeline (`pap-timeline`, `pap-step`) for immutable decisions, shared status chips, and existing older/latest pagination actions.
- `/operations/verification`: Creator Pipeline Approvals Focus queue plus decision panel. Queue items keep fixed reference/state/action slots; the selected review's facts, evidence downloads, verdict form and history follow `pap-panel` blocks. Assignment and reassignment use Settings form cards. Selection has an explicit pressed state; content transitions consume the shared motion recipe. At phone width list and decision panel stack without hidden data or horizontal overflow.
- `/business-intake`: Creator Pipeline Settings editable sections combined with Approvals Focus. Organization picker is a shared Select; intake queue at the side of a form card. Intake identity, condition, permission checks, fee and currency fields follow shared form controls and Settings panel spacing. Private evidence uses the same list-row and upload-control family. Narrow screens stack the queue and editor, retaining native validation, custody guards, idempotency and file restrictions.
- `/operations/moderation`: Creator Pipeline Approvals Focus queue and `DecisionPanel`. Report and reference forms use shared controls. Queue rows use status chips and explicit selection/claim/release actions. Evidence and policy text use soft surfaces (never colored edge stripes). The decision and appeal forms retain independent pending/error states and revision guards. Audit events use the Submissions timeline. Phone layout stacks existing content and keeps every action reachable.
- `/operations/dashboard`: Creator Pipeline Home cards / Admin Activity overview. Shared Calm header, queue cards with quiet metadata, shared status chips and button links. No invented metrics: the actual queue items and prerequisite/denied/unavailable states remain the source of truth.
- `/operations/dashboard/queues/[key]`: The same overview/queue card pattern for one queue, retaining its route and endpoint.

## Shared states and motion

All boundaries preserve authentication restoration, access-fingerprint remounting and retry behavior. Empty/access/error faces follow `components/faces/calm-face.tsx`; skeletons follow `components/ui/row-skeleton.tsx`; card and list entrance uses the shared `pg-contentIn`/list recipe rather than new feature keyframes. Buttons and field focus/hover/press/disabled states come only from shared primitives. Page tabs must be real locale-aware links and reflect the active route. EN/AR strings and bidi references remain intact. Feature CSS is restricted to token-consuming layout recipes with logical properties; no feature color, font, radius, shadow, or keyframe definitions.

## Reference source files studied

- `components/proto/page-header/page-header.tsx`, `styles/proto-page-header.css`
- `components/proto/approvals/approvals-parts.tsx`, `styles/proto-approvals.css`
- `components/proto/settings/settings-page.tsx`, `styles/proto-settings.css`
- `components/admin/activity-page.tsx`
- `components/creators/row-primitives.tsx`
- `components/budgets/budgets-workspace.tsx` and the older `components/marketing-workspace/workspace.*` (not the target header)
