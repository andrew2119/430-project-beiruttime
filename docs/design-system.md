# Shared interface foundation

Beirut Time opens into a marketplace dashboard. Public browsing remains available; signed-in sections follow existing roles. Navigation visibility is never backend authorization. English and Arabic share the same pages and components.

## Ownership and entry points

`web/app/globals.css` is the only ordered global entry. `web/styles/tokens.css` owns primitive values, semantic themes, scales, layers and compatibility aliases. Feature code consumes these values; it does not define another palette, type scale or motion ladder. `web/styles/typography.css` supplies opt-in type recipes in the base layer, before motion and shared controls. Component recipes belong in the components layer, below named composition and utilities.

New composition uses `--bt-*` properties and `bt-*` classes. Existing token and class spellings are migration bridges, not an alternative system. Their computed declaration values are preserved while pages move onto the foundation. Do not add consumers of legacy-only names. Removing the final consumer also removes its bridge.

The public component boundary is `@beirut-time/ui`; `@/shell/primitives` remains a compatibility re-export. Features must not deep-import private implementations. [Frontend rules](frontend-rules.md) governs every change, including recipes used twice becoming one shared piece and approved designs propagating to all affected pages.

## Theme and colour roles

The server reads the existing `bt-theme` cookie and stamps `data-theme` before rendering. The only offered themes are `light` and `dark`; missing or invalid preference selects light. Runtime switching uses the same preference, without a second page tree. The unstamped-document compatibility palette is not a third selectable theme.

Every name in this section is prefixed `--bt-`:

| Surface or use | Fill | Ink |
|---|---|---|
| Page | `background` | `foreground` |
| Card | `card` | `card-foreground` |
| Floating surface | `popover` | `popover-foreground` |
| Muted region and its secondary copy | `muted` | `muted-foreground` |
| Quiet secondary copy on page/card | Page/card fill | `muted-foreground` |
| Primary action | `primary` | `primary-foreground` |
| Destructive action | `destructive` | `destructive-foreground` |
| Quiet accent region | `accent` | `accent-foreground` |

Use `primary-ink` and `destructive-ink` for coloured text, links and marks on the proven opaque page/card/popover grounds, not the saturated fills. They are not ordinary-text ink on arbitrary tinted grounds: dark primary/destructive ink on muted/accent is only about 4.34:1. Use the paired foreground there or prove another pairing. Dark mode deliberately separates ink from fill. `success-ink` and `tone-green/amber/blue/rose/plum` provide readable state/choice ink. A state also needs words or an icon; colour is never its only meaning. `border`, `input` and `ring` serve different purposes; a decorative hairline is not evidence of sufficient focus contrast. `ink-on-dark` is reserved for fixed dark media/scrims, whose surface does not change with the theme.

The actual canonical `muted-foreground`/`muted` pair clears ordinary-text AA with margin: about 5.27:1 in light and 4.795:1 in dark. Dark canonical secondary ink is neutral 67% lightness. Existing secondary ink and its utility export retain the exact 65% value through `compat-muted-foreground`; they remain migration debt, not an approved new pair. New shared recipes consume canonical roles, not that compatibility utility.

Primitive burgundy, sand, brass and status ramps stay in the token owner. Light retains its existing blue primary and dark its existing burgundy fill. Sprint 1's paint stays unchanged through compatibility values. Canonical semantics/materials rebind at the nearest explicit theme boundary, including within existing header descendants; legacy header/ancestor scopes only define legacy properties and cannot reassign canonical roles.

## Type, Arabic and numbers

Latin uses the local Lexend Deca variable face; Noto Sans Arabic supplies Arabic glyphs. Both local files and their licenses are in `web/app/fonts/`. Neither theme nor locale loads a remote font. `font-body` follows the nearest language attribute; `font-latin` and `font-arabic` expose the local faces without duplicating font declarations.

The `text-caption/small/body/lead/heading/display` steps are 0.75/0.8125/1/1.125/1.5/2rem. Body leading is 1.5; heading leading is 1.3. `weight-regular/medium/strong/heavy/black/display` are 400/500/680/750/800/820. Do not round the expressive weights to hundreds. Rem sizing permits text growth; typography never imposes a fixed block height or clips diacritics.

- `bt-text`, `bt-heading` and `bt-caption` use logical start alignment, shrinkable text and anywhere wrapping. They do not globally truncate names or identifiers.
- `bt-number` uses `font-numeric`, a tabular system monospace stack. The local display face has proportional digits; setting a numeric feature on that face does not create missing tabular glyphs. Use the numeric recipe for compared/updating columns, not all ordinary text.
- `bt-ltr` isolates a watch reference, URL or explicitly LTR amount inside Arabic. Put it on the value, not an entire row. Localized number formatting remains the data renderer's responsibility.

The root already stamps both `lang` and `dir`. Use inline/block dimensions, start/end alignment and logical padding. Do not reverse a whole page to repair one icon or identifier. The existing desktop rail placement remains unchanged until its shell slice; all new composition must respect RTL without a separate Arabic tree.

## Spacing, geometry and elevation

`space-0/half/1/2/3/4/5/6/8/10/12/16` are 0/2/4/8/12/16/20/24/32/40/48/64px. Prefer semantic `gap-title/block/row/group/cluster/content` and `pad-header-block/inline`, `pad-card-block/inline` when composing headers and cards. These roles share the scale and adapt together; pages do not invent local ladders.

`radius-sm/md/lg/xl/2xl` are 4/6/8/12/16px through one 8px base. `radius-navigation/frame` retain 22/24px on desktop and 20px on phone shell surfaces. `radius-raised/raised-small` are 10/8px. `radius-pill` is for pills, never an excuse to turn every surface into a capsule.

`shadow-hairline/low/raised/menu/dialog/frame/key` describe elevation roles and adapt to the theme. Phone frame tokens select the short `phone-shadow-frame` at or below 850px, whether the frame carries its own theme attribute or sits under a themed wrapper. The owned responsive token selector matches theme specificity; component recipes remain zero-specificity. Glass roles and gloss are centrally owned, not per-page colours. Actual fallback, backdrop support and overlay integration are proved with their component slices.

`control-height` and `control-target` begin at 32px for desktop rows. At the 850px shell boundary they become the 36px drawn control and 44px target; chips draw at 32px. Form/input sizing and the coarse-pointer 16px font floor are separate contracts, not inferred from a painted-control token. Existing pages retain their current recipes until rebuilt.

Desktop dialogs will consume `window-read: 44rem` or `window-wide: 60rem`, constrained by viewport space. These are desktop windows, not phone-width panels. Responsive layout must also work in a narrow container on a wide screen.

## Layer ladder

All values come from the token owner. A local stacking context must still be reviewed; a large number alone cannot place a surface above a sibling context.

| Token | Value | Responsibility |
|---|---:|---|
| `--bt-layer-content` | 1 | Local content/decorative content plane |
| `--bt-layer-pinned` | 10 | Sticky page chrome |
| `--bt-layer-navigation` | 20 | Navigation rail, top bar and dock |
| `--bt-layer-shade` | 40 | Modal shade |
| `--bt-layer-window` | 50 | Dialog or sheet |
| `--bt-layer-menu` | 60 | Nested popover/menu |
| `--bt-layer-toast` | 80 | Reachable notifications above modals |
| `--bt-layer-loading` | 95 | Emergency loading surface |
| `--bt-layer-skip` | 110 | Keyboard skip link |

The three existing local-content/loading/skip aliases resolve to the same ladder and keep their exact values. Features cannot define a new ladder or provide numeric fallbacks.

## Composition and later foundations

The root mounts shell, locale/direction, query, theme and installation providers once. Pages do not add another main, sidebar, dock or toaster. Existing `PageHeader` and `PageLayout` remain the composition boundary while the signed-in shell/new-page template is completed.

The shared package already exposes buttons, links, named inputs, segmented selection, Radix surfaces, decoded image frames, skeletons and state faces. Their comprehensive state, gesture, toast-reach and drawing-board review belongs to the component slice. An export existing today is not proof of those later contracts. New elements are demonstrated with the real shared composition before pages adopt them.

Motion values in the token owner are preserved, not retuned here. The motion slice owns the duration/curve script readers, shared keyframes, reduced-motion contracts, theme transition and navigation icon behavior. Pages never add private keyframes, duration literals or a second primitive family.

## Quick checks and proof limits

Run lint with zero warnings, type checks and `ui:rules`. `node --test web/scripts/foundation-tokens.test.mjs` checks the graph and 271-retained-declaration fingerprint; a bounded selector/specificity/media/inheritance model covers opposite-theme headers, both themed phone-frame host arrangements and 128 legacy source-cascade arrangements. It also checks the actual muted pair, other opaque contrast pairs, scales/layers, local fonts and opt-in type. The focused existing design-system tests cover SSR preference and preserved component contracts.

Static token graphs and numerical colour pairs do not prove browser cascade, font metrics, mixed-script shaping, real focus contrast, glass compositing, page fit or runtime/render parity. The bilingual/theme/desktop/phone drawing-board matrix, 200% text/narrow containers, device checks and all other heavy evidence remain owed. See [frontend rules](frontend-rules.md) and [design verification](design-verification.md).
