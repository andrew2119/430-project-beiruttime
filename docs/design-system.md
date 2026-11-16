# Shared interface foundation

The application opens into a dashboard, not a marketing landing page. Public browsing remains available; authenticated sections are filtered by the existing registration roles. Every visible tab opens a real route. Navigation visibility is not backend authorization.

## Design-system ownership

The shared interface uses Lexend Deca, a four-tier token system, Light/Dark palettes, base/motion/UI/shell/mobile recipes, Calm page headers, Pane tabs, measured sticky-header condensation, native controls, Radix surfaces, Sonner outlet, skeletons and calm state faces. Navigation, copy, icons and session APIs belong to Beirut Time.

`web/app/globals.css` is the single ordered CSS entry. `web/styles/tokens.css` is the only global design-token owner. Feature styles consume tokens; they do not define palettes, fonts or animation ladders. Layout adapters stay with their features.

Arabic support is supplied by logical-property adapters, Radix direction provider, mirrored phone drawer and isolated LTR references. Lexend Deca remains the Latin face; local Noto Sans Arabic supplies glyphs it does not contain. Both fonts ship locally with their licenses.

## Page composition

The root mounts the shell, theme, locale/direction, query and installation providers once. Pages must not add another main, sidebar or dock.

```tsx
import { PageHeader, PageLayout } from '@/shell/page-header';
import { Button, Card, Input, Label } from '@beirut-time/ui';

<PageLayout>
  <PageHeader title={t.title} count={t.description} tools={filters}/>
  <Card>{content}</Card>
</PageLayout>
```

PageHeader accepts translated title/count, lead, media, tag, actions, tools, views, nav, status, notice and search slots. Actions retain page-owned handlers and permissions. The shared component owns header spacing, phone fitting and measured sticky behavior. PageLayout supplies the 24px/28px desktop and 12px phone gutters. Do not double-pad a nested layout.

## Token contract

- Surfaces: `background`, `card`, `popover`, `muted`, `accent`, `ds-canvas`.
- Text: `foreground`, `card-foreground`, `popover-foreground`, `muted-foreground`, `accent-foreground`.
- Actions: `primary` fill with `primary-foreground` label; `primary-ink` for colored text/icons/lines. Destructive fill and ink are similarly separate. Focus uses `ring`; edges use `border` and `input`.
- Spacing: `ds-space-1/2/3/4/5/6/8` = 4/8/12/16/20/24/32px; named `ds-gap-*` and `ds-pad-*` express header/card rhythm.
- Radius: `radius-sm/md/lg/xl/2xl` = 4/6/8/12/16px. Rail/tray are 22/24px desktop and 20px phone.
- Weight: `ds-weight-strong/heavy/black/display` = 680/750/800/820, not rounded to conventional hundreds.
- Elevation: `ds-shadow-border/small/medium/menu/modal/shell`, with shared gloss and hairline tokens.
- Motion: `ds-motion-fast/popover/overlay/theme/expressive/press/shimmer/image-reveal` = 150/200/300/450/600/130/1600/180ms, with the shared easing vocabulary. Global reduced motion is the single baseline.

All names above are CSS custom properties prefixed `--`. The old `--muted` text usage must become `--muted-foreground`: the muted token is a surface. Likewise, old colored `--accent` ink becomes `--primary-ink`. Transitional surface/brand/spacing aliases map into the same token system, not another palette.

## Primitives

`@beirut-time/ui` is the sole implementation; `@/shell/primitives` is a compatibility re-export.

- Button and ButtonLink share default/outline/ghost/destructive variants, default/sm/icon sizing, and the optional `chonk` raised plinth. Native form semantics and disabled behavior remain intact. ButtonLink's recipe is server-safe.
- Input, Textarea, Label, Checkbox, Radio and lazy Select retain native naming/association or the shared menu keyboard contract. When replacing a named native select, retain its submitted value with a hidden field. Select's search labels follow EN/AR direction.
- StatusBadge, Segmented/Group/Item, HeaderTabs and FilterChips share the selected-state, measurement and motion recipes. FilterChips takes translated accessible labels.
- Dialog/Sheet, DropdownMenu and Popover use shared Radix portal, collision, keyboard, dismissal and focus behavior. DialogContent requires a translated closeLabel.
- ImageFrame reserves geometry and reveals decoded pixels. Marketplace media policy, bounded retries and credit/zoom behavior remain domain-owned.
- Skeleton, AnimatedList, State, LoadingOverlay, ScrollRegion and ScrollBox provide shared loading, arrival/reorder, calm empty/error and accessible overflow behavior. Pass translated state copy and region names.
- AuthCard, AutoHeight, Switch, RowSkeleton, CardHead, SectionState, LoadingRows and Notice centralize auth, Settings, skeleton and compact state recipes. Feature modules compose these rather than copying another control.
- The shell mounts Toaster once; pages call `toast` with translated messages. It measures actual toast-stack clearance without reserving room for absent integrations.

## Shell, preferences and phone behavior

The desktop rail stays on the left at 224px, including Arabic; its content still reads RTL. Brand, profile/role, Account, Settings and theme controls share fixed rail placements. Unknown/unavailable session restoration never grants a private tab. Badge counts must be real service state, never invented zeros.

The larger marketplace navigation scrolls within the rail so its profile footer stays anchored. Dashboard cards stack into one column on phone.

Settings exposes the real session profile/account door, EN/AR language selection, and Light/Dark appearance miniatures. It does not invent profile-edit endpoints. The existing `bt-theme` cookie is stamped before paint; runtime changes use the shared 450ms root View Transition and reduced-motion fallback.

The single shell breakpoint is 850px. A persistent tray sits between the 48px top bar and safe-area-aware quick dock. Both menu doors share one modal drawer. Escape returns focus to its invoker; navigation hands focus to the destination main. Compact controls paint at 36px inside a 44px target; phone inputs remain at least 16px. CSS/container layout changes never create a second page tree.

Installation remains progressive and online-first. The worker caches public static assets only, and updates require explicit consent. The self-contained offline and root-fatal faces intentionally retain a platform-font fallback when the application/font bundle cannot load. No offline transaction is confirmed or queued. Public icon-cache v2 retires the old presentation assets only through the existing update-consent lifecycle.

## Shared recipe inventory

- `web/styles/` owns base, auth, faces, controls, page headers, shell, mobile, sidebar, sticky headers, tabs, settings and motion. Global spacing and glass materials stay in `tokens.css`; features consume them.
- The shell centralizes title fitting, header tips, sticky measurements, navigation warming, theme lifecycle and phone keyboard/drawer behavior. Existing registration roles and RouteFocus/history remain authoritative.
- AuthCard, AutoHeight, Switch, CardHead, SectionState, LoadingRows and Notice are shared UI primitives, not local feature copies.
- Motion includes content/list/dialog entry and exit, skeleton pulse, image reveal, drawer/scrim and sticky-progress keyframes. Arabic drawer keyframes mirror the horizontal translation; reduced motion is global.
- Light and Dark are the two selectable themes. Classic values remain a compatibility token set, not a third option.
- Real account APIs determine available profile/security actions. Counts require real service state; no fabricated notification/chat integrations or unused dock reservations are introduced.
- ImageFrame owns reserved geometry/decode reveal; callers own media URL policy, retries and attribution.

See [design verification](design-verification.md) for checks, reproduction and evidence limits.
