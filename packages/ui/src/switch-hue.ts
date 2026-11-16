/**
 * The calm colour code of in-tab switches: one meaning per
 * option label, the same on every page. green = done, live or in; amber = waiting or
 * not yet; blue = new, open or for information; rose = stopped or needs care; plum =
 * a spare fifth for a group with no status meaning. A choice with no meaning of its
 * own (All, Everything, ranges, sort, layout) has none and reads in plain ink, so a
 * colour always means a status. The tones are `--tone-<hue>` in styles/tokens.css.
 *
 * Which label means what is kept once, in web/styles/tabs.css ("Words in the calm
 * colour code"): a switch option carries its text label as `data-label`, so the map
 * is one copy in the shared stylesheet, not one in every page's script. An option
 * whose label is not plain text names its hue (`data-hue`).
 */
export type SwitchHue = "green" | "amber" | "blue" | "rose" | "plum";
