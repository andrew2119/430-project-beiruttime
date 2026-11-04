const ANIMATION_PACING_TOKENS = new Set([
  "--ds-motion-fast",
  "--ds-motion-popover",
  "--ds-motion-overlay",
  "--ds-motion-theme",
  "--ds-motion-expressive",
  "--ds-motion-press",
  "--ds-motion-shimmer",
  "--ds-motion-image-reveal",
]);

function parseMotionToken(name: string): number | undefined {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  const match = /^(-?\d*\.?\d+)(ms|s)$/.exec(raw);
  if (!match) return undefined;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return undefined;
  return match[2] === "s" ? value * 1000 : value;
}

export function readMotionToken(name: string): number | undefined {
  if (typeof window === "undefined") return undefined;
  const reduced =
    ANIMATION_PACING_TOKENS.has(name) &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return parseMotionToken(reduced ? "--ds-motion-reduced" : name);
}

/** The user's reduced-motion preference, read at call time (never during a
 *  server render). Shared by the list-motion primitive and the segmented
 *  thumb so JS-driven motion honours the same media query the global CSS
 *  baseline in styles/motion.css does. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
