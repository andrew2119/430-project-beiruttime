# Buyer area → Creator Pipeline mapping

Source (read only): `/Users/andrew/.harness/homes/creator-pipeline/firstmate/projects/creator-pipeline-middleware/frontend`.

This inventory was completed before the design-system usage contract was available. Styling implementation must wait for that contract, then consume its exported primitives. Existing routes, authorization, amounts, operation keys, Arabic/English dictionaries, and API contracts remain unchanged.

## Shared recipes

- **Page frame and header:** `components/proto/page-header/page-header.tsx`, `styles/proto-page-header.css`. Use the one Calm card header, its title/count line, optional navigation tabs, named content gaps and card padding. No oversized editorial headings or feature-specific page gutters.
- **Controls:** `components/ui/button.tsx`, `input.tsx`, `select.tsx`, `checkbox.tsx`. Use the shared small chonk action, outline secondary action, common field and menu-backed select (Creator Pipeline does not use native single-choice selects). The kit owns hover, press, keyboard focus, disabled and busy appearances. Phone controls paint 36px inside a 44px hit target; input text is 16px.
- **Lists:** `components/ui/animated-list.tsx`, `styles/motion.css`. Keyed rows share exit holds and FLIP reorders. Initial data and pagination appear atomically; only actual live arrivals receive entrance animation. Never invent staggered page/list keyframes.
- **States:** `components/proto/states/state-face.tsx`, `styles/proto-states.css`. Compact Calm card for section empties/locked/error states; full shared face for unavailable page content. Keep dependency failures independent and never replace a failed money/permission read with sample success. Loading uses the common skeleton.
- **RTL/theme:** inherit the shell font, direction, light/dark switch and page transitions. All feature layout uses logical axes. Monetary amounts and opaque identifiers remain isolated with `BidiReference`; no second Arabic tree.

## `/buyer`

**Reference:** Marketing Home (`components/proto/home/home-page.tsx`, `card-head.tsx`, `ui-bits.tsx`, `styles/proto-home.css`) and the campaign creator rows.

- Header title = buyer workspace, count line = existing intro, eyebrow preserved as the header's quiet tag/lead rather than a second feature heading.
- The two dashboard section cards correspond to Home's independently loaded cards: active bids and reservations. Their title/count heads follow Home's compact card-head rhythm.
- Activity rows adopt a common compact card/list recipe; status badges consume the shared badge tones, with sample marking kept as a quiet fact. Facts are aligned definition rows; actions use shared links rather than restyled anchors.
- Desktop has two balanced columns; 390px stacks the same sections in DOM order, with wrapping identifiers/actions.
- Restore/error/signed-out/denied states use shared skeleton/state faces. Each unavailable source retains its own section. No cached previous-owner data becomes visible.

## `/buyer/auctions/[listingId]` and watch-detail maximum slot

**Reference:** campaign detail header plus `components/proto/deal-settings-sheet.tsx` / new-campaign form fields (`styles/proto-new-campaign.css`).

- The dedicated route uses the shared detail/page header and a secondary back action, not an invented bidding hero.
- The maximum panel is a shared card containing the existing privacy copy, standard field, quiet hint and grouped actions. Previewed fees use the compact finance fact-row recipe.
- Preserve all stages: restoring, unavailable, denied, scheduled/ended, quoting, quote expiry, stale revision, sending, acknowledgement, uncertain and offline. Review and confirm remain separate operations. Do not add a dialog or replace the route/slot with a new bid engine.
- The dedicated route and watch slot share exactly the same form component. Phone input stays full width; actions wrap without overflow.

## `/checkout`

**Reference:** campaign settings/new-campaign form card and Marketing Home's secondary activity card.

- Header uses the common Calm card; watch/quote reference form is the primary card and reservation history is the secondary card. All existing labels/help remain intact.
- Availability, uncertain writes and payment limitations use the shared notice/state recipes (no accent stripe or invented color panel).
- Orders use keyed compact rows with identifiers, state and sample fact; no per-feature anchor treatment.
- Desktop uses a primary/secondary card grid; 390px stacks form then orders. Reserve stays disabled until the authoritative fixed-price availability and quote reference permit it.
- Keep boundary restore/sign-in/outage, empty orders, failed availability/orders, reservation denial, uncertainty/retry and successful reservation visible without inventing payment success.

## `/checkout/[id]`

**Reference:** campaign detail + finance detail facts and Home activity rows.

- Shared detail header carries the order identifier in its quiet count/metadata line.
- The order summary and history are common cards. Summary definition rows use finance's aligned label/value treatment; history is a keyed activity list with quiet timestamps and revision metadata.
- Payment hold and intake remain existing inline permission-gated forms using standard fields, textarea and actions. No new modal or operational workflow.
- Preserve invalid ID, restoring, outage, denied detail, sample, pending payment, payment unknown, expiry, stale revision, uncertain write, receipt and saved states.
- At phone width the cards and fact rows stack; long identifiers wrap and all enabled actions retain full targets.

## `/prices` (including selected quote query)

**Reference:** finance expenses (`app/(app)/finance/expenses/_view.tsx`, `styles/finance.css`) plus shared header navigation and new-campaign fields.

- Prices/Inbox/Buying links move into the shared header's real-link tabs; they remain links with `aria-current` and locale-preserving URLs.
- Quote creation and selected quote use balanced common cards. Source/purpose/currency controls use the kit's select; numeric/reference fields use its input and existing input modes.
- Fee breakdown follows finance's tabular label/value rows. Payable is a strong total separated by the kit border token, not a large invented accent heading.
- History uses keyed list cards with outline view action, amount and quiet sample/reference facts. Empty, loading and failure states use the common faces.
- Preserve sample policy, source verification, expiry, commission basis, quote review and all existing validation/error references. No binding/purchase behavior changes.

## `/buying` (readiness, offer drafts)

**Reference:** Marketing Home's status cards, campaign settings forms, Draft Board (`components/drafts/DraftBoard.tsx`) and finance facts.

- Same shared header navigation as Prices and Inbox.
- Reservation/readiness card and offer-draft editor use common card/form spacing. Payment routes remain visibly unreleased and disabled; no success-colored readiness invention.
- Readiness facts use standard muted metadata and badges. A bound quote reuses the exact quote-fee component from Prices.
- Draft list adopts keyed compact rows with money, revision, reference, edit and disabled send controls. Editing keeps the same form and cancels without a new route.
- Preserve not-selected/unavailable/denied/binding-unavailable sub-source statuses, draft create/edit validation, saved feedback and no-commitment copy. Stack cards and paired fields naturally at 390px.

## `/inbox`

**Reference:** `components/proto/notification-panel.tsx`, `styles/proto-notifications.css`; optional preference uses `components/proto/settings/settings-parts.tsx` Switch.

- The existing page remains a page, not the reference's popover. Its header/tabs use the shared kit while its notice rows adopt the soft notification-card vocabulary, quiet metadata and a fixed unread indicator. Remove the invented left stripe.
- Required/optional, read state, event time, sample and resource revision remain visible. Mark read, clear and open retain their existing independent authenticated operations and allowlisted destinations.
- The optional notice preference uses the shared switch with the current revision guard, pending/disabled behavior and failure retry, not a feature-colored checkbox.
- Keyed list transition handles clear/removal; pagination is atomic. Do not invent grouping, archive endpoints, bulk operations or mark-on-open behavior absent from Beirut Time.
- Shared empty inbox face, list skeleton and independent preference/list/marker/link failure states. On phone, actions wrap below content; metadata and opaque references wrap without horizontal scrolling.

## Verification target

For each route: English/Arabic × light/dark × desktop/390px real viewport; compare the reference header/card/form/list/state patterns in an isolated chrome-devtools-axi session. Exercise hover/focus/press, keyboard navigation, theme transition, live-list changes, loading/empty/error/locked states and existing mutation safeguards. Feature tests may change only where markup changes require it.
