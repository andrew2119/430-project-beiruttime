const legacyPacing = new Set([
  '--ds-motion-fast', '--ds-motion-popover', '--ds-motion-overlay',
  '--ds-motion-theme', '--ds-motion-expressive', '--ds-motion-press',
  '--ds-motion-shimmer', '--ds-motion-image-reveal',
]);
const pacing = new Set([
  '--bt-motion-press', '--bt-motion-fast', '--bt-motion-popover',
  '--bt-motion-menu', '--bt-motion-overlay', '--bt-motion-exit',
  '--bt-motion-image', '--bt-motion-gentle', '--bt-motion-theme',
  '--bt-motion-icon', '--bt-motion-pulse',
]);

/** Read at the action, never cache a theme/preference-dependent CSS value. */
export function readMotionToken(name: string, element?: Element): number | undefined {
  if (typeof window === 'undefined' || typeof document === 'undefined' || typeof getComputedStyle !== 'function') return undefined;
  const reduced = prefersReducedMotion();
  const token = reduced && pacing.has(name) ? '--bt-motion-none' : reduced && legacyPacing.has(name) ? '--ds-motion-reduced' : name;
  const raw = getComputedStyle(element ?? document.documentElement).getPropertyValue(token).trim();
  const match = /^(\+?\d*\.?\d+)(ms|s)$/i.exec(raw);
  if (!match) return undefined;
  const value = Number(match[1]) * (match[2].toLowerCase() === 's' ? 1000 : 1);
  return Number.isFinite(value) && value >= 0 ? value : undefined;
}

/** A discrete input boundary, not a per-frame style driver. */
export function markMotionInput(target: HTMLElement, input: 'pointer' | 'keyboard'): void {
  target.dataset.btMotionInput = input;
}

/** Preference is queried when needed, including during an interrupted release. */
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
