# Buyer page patterns

Buyer pages consume the shared design system. Existing routes, authorization, amounts, operation keys, EN/AR dictionaries and API contracts remain unchanged.

## Shared recipes

- PageLayout and Calm PageHeader own gutters, title/count lines, optional navigation and named control gaps. No feature-specific hero or heading scale.
- Shared Button, Input, Select and Checkbox own hover, press, focus, disabled and busy states. Select uses a menu with native form-value bridging where required. Compact phone controls paint at 36px within 44px targets; input text is at least 16px.
- AnimatedList owns keyed exits and reorders. Initial data and pagination appear atomically; only actual live arrivals enter individually.
- SectionState, State and skeletons cover compact/page empties, locked and failed reads. Independent dependencies remain independent; no sample success replaces a failed money/permission read.
- Theme, font, direction and page transitions are shell-owned. Layout uses logical axes; `BidiReference` isolates money and opaque identifiers.

## `/buyer`

Two independent dashboard cards hold active bids and reservations, with CardHead title/count rhythm, status badges, aligned facts and quiet sample markings. Desktop has two columns; phone stacks in DOM order. Preserve restoring, unavailable, signed-out and denied states without exposing cached previous-owner data.

## `/buyer/auctions/[listingId]` and watch-detail maximum slot

The detail header and maximum form use shared cards, fields, hints and actions. The route and watch slot share one form. Preserve restoring, unavailable, denied, scheduled/ended, quoting, expiry, stale revision, sending, acknowledgement, uncertain and offline states. Preview and confirm remain separate operations; no new bid engine or modal.

## `/checkout`

The quote/reference form is the primary card; reservation history is secondary. Notices describe availability, uncertain writes and payment limitations without invented success. Reserve stays disabled until fixed-price availability and quote authority permit it. Preserve independent availability/order failures, denial, uncertainty and retry.

## `/checkout/[id]`

Quiet order reference in the detail header; summary fact rows and keyed history in cards. Existing permission-gated hold/intake forms stay inline. Preserve invalid ID, restoring, outage, denied, sample, payment unknown, expiry, stale revision, uncertain write and saved receipt states. Long references wrap on phone.

## `/prices`

Prices/Inbox/Buying are real locale-aware links with `aria-current`. Quote form and selected quote use balanced cards, shared Select/Input and aligned fee rows. A strong total is separated by the border token. Preserve source verification, sample policy, expiry, commission, quote review, validation and references.

## `/buying`

Readiness, offer editor and keyed draft rows use shared cards/fields/facts. Unreleased payment routes remain visibly disabled. Bound quotes reuse the fee component. Preserve independent source statuses, create/edit validation, revision/reference metadata, saved feedback and no-commitment copy; edit/cancel stays in the current form.

## `/inbox`

A full page with shared header/tabs, soft notice cards, fixed unread indicator and quiet metadata. Required/optional, read state, event time, sample and resource revision remain visible. Read, clear and open remain independent authenticated operations with allowlisted destinations. The optional preference uses Switch with revision/pending/disabled/retry guards. Keyed removal is shared; pagination is atomic. No invented grouping, bulk operations or mark-on-open behavior.

## Verification target

For each route: EN/AR, light/dark, desktop/real 390px viewport; shared header/card/form/list/state geometry, hover/focus/press, keyboard behavior, theme transition, live-list changes and mutation safeguards. See [validation](VALIDATION.md) and [the design contract](../../../docs/design-system.md).
