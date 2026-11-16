# Shared interface foundation

Beirut Time opens into a marketplace dashboard. Public browsing remains available; signed-in sections follow existing roles. Navigation visibility is never backend authorization. English and Arabic share the same pages and components.

## Ownership and entry points

`web/app/globals.css` is the only ordered global entry. `web/styles/tokens.css` owns visual primitive values, semantic themes, scales, layers and compatibility aliases. `web/styles/bt-motion.css` is the one canonical owner of new duration/curve tokens, keyframes, motion recipes and reduced-motion handling. Feature code consumes these contracts; it does not define another palette, type scale or motion ladder. `web/styles/typography.css` supplies opt-in base recipes before motion and shared controls. Component recipe hosts use :where in the components layer, below named composition and utilities.

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

## Motion and input

The canonical owner is `web/styles/bt-motion.css`, imported after the frozen compatibility sheet. Existing Sprint 1 motion is not retuned without its page rebuild and runtime proof. The old sheet is exact-hash frozen, gains no new consumer, and is deleted with its import when the last old consumer is rebuilt. Twenty fixed timing declarations remain in the visual token file only for compatibility. The checker rejects new/changed files naming the old motion classes/keyframes, including class-recipe strings. See [frontend rules](frontend-rules.md) for the exact frozen boundary.

The `--bt-motion-press/fast/popover/menu/overlay/exit/image/gentle` steps are 130/150/180/200/250/120/180/120ms. Theme crossfade is an occasional 450ms document operation; opt-in icon arrival has a 600ms single-play arc; 1600ms is a loading/wait period and 5000ms a safety deadline, never interaction latency. The default reduced-motion floor matches the old instantaneous step, while script-driven canonical releases read the zero-time `none` token.

Curves are `--bt-ease-out` for response, `travel` for movement, `drawer` for edge settling, `colour` for colour/opacity and `constant` for constant motion. Durations are public through `@beirut-time/ui/motion`; curve reads are separately loaded through `@beirut-time/ui/motion-easing`. Both resolve CSS at the action. Missing/unreadable values choose an immediate result, never a duplicate literal timing table. A safety deadline is not shortened by reduced motion.

Shared recipes cover trigger-origin surfaces, centered windows and coordinated shades; bottom/end/responsive/phone-only sheets (850px boundary, logical end in RTL); the sole reversible 0fr/1fr fold; press feedback; one-shot answer arrival; explicit live-row enter/exit/reorder; decoded-pixel fades and flat placeholders. Opacity-only one-shot arrivals share a frame rather than separate shade/list copies. Reversible surfaces, shades and row exits use retargetable CSS transitions, not restarting keyframes. No gradient shimmer, decorative public-report entrance or private feature keyframe is added. Section rise is opt-in and occasional, not a repeated page/tab reading effect. F3 must keep exiting surfaces mounted through transition completion, cancel that exit hold on reopen and settle reduced/keyboard exits immediately; an animation-name-only presence detector is insufficient. Modern entry uses @starting-style; the one-time data-starting fallback is not a per-frame driver. Measured drag release and velocity/scroll ownership belong to the shared component implementation, never a CSS variable updated on a parent every frame. Shade and surface share both ordinary exit pacing and the longer measured drag-settle step.

Reduced motion removes movement, freezes placeholder/icon loops, makes decoded images atomic and keeps only named gentle fades. `--bt-motion-kept-animation/transition/iterations` are registered non-inheriting per-part floor properties, not a global exemption. Keyboard/high-frequency entry points use `data-bt-motion-input="keyboard"` or `data-bt-motion="off"` for immediate state changes. The public `markMotionInput` helper marks discrete focus/key/pointer boundaries; it is never a frame driver. The new switch marks keyboard focus/press before CSS feedback as well as skipping its keyboard snapshot. New motion must declare frequency and purpose before using an arrival recipe.

`ThemeSwitch` requires translated next-action labels and shares the root preference/cookie provider. Keyboard clicks, reduced motion, unsupported APIs or missing tokens apply immediately; pointer snapshots are cancellable and late stale callbacks cannot overwrite a newer request. Only this new control stamps the canonical snapshot marker. Existing preference controls retain their pacing, target and persistence statements; shared request ownership only cancels obsolete snapshots. Mixed old/new requests cannot let a late callback restore the wrong theme, and snapshot/curve code is not imported by the old control path. The new control is not added to navigation until its reviewed shared composition is ready.

`NavigationIcon` covers every registered marketplace destination. Its slot is fixed and decorative; the link owns its accessible name, busy state and focus. Active/pending/busy remain static by default. Only an explicitly opted-in occasional pointer arrival plays an arc; keyboard never does, and hover never replays a glyph. Pending indication can use an opacity-only wait, not a moving label. Current Sprint 1 route icons remain untouched until the shell rebuild.

## Quick checks and proof limits

Run lint with zero warnings, type checks and `ui:rules`. `node --test web/scripts/foundation-tokens.test.mjs` checks the visual-token graph and 271 retained facts, opposite-theme headers, both phone-frame hosts and 128 legacy source-cascade arrangements. `node --test web/scripts/motion-rules.test.mjs` checks canonical ownership, frozen/retired motion, new/changed consumer rejection, shared recipes, budgets and the unchanged old provider path. The focused `tests/motion.test.ts`, `tests/motion-components.test.ts`, `tests/theme-provider.test.tsx` and existing design-system tests cover CSS token reads, interrupted theme requests, translation, modality and navigation registration/state contracts. These are code/source-model proofs, not browser feel or frame recordings.

Static token graphs and numerical colour pairs do not prove browser cascade, font metrics, mixed-script shaping, real focus contrast, glass compositing, page fit or runtime/render parity. The bilingual/theme/desktop/phone drawing-board matrix, 200% text/narrow containers, device checks and all other heavy evidence remain owed. See [frontend rules](frontend-rules.md) and [design verification](design-verification.md).
