/**
 * Brand values that must be serialized as plain strings outside the stylesheet
 * (the browser viewport `theme-color` meta cannot read a CSS custom property).
 * The single source of truth stays `styles/tokens.css`; `lib/brand.test.ts` proves
 * this sRGB encoding matches `--color-rebellion-700` there.
 */
export const BRAND_THEME_COLOR = "#8B1A1A";
