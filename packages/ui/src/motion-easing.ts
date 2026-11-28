/** Kept separate from duration reads so only measured-release users load it. */
export function readEasingToken(name: string, element?: Element): string | undefined {
  if (!name.startsWith('--bt-ease-') || typeof window === 'undefined' || typeof document === 'undefined' || typeof getComputedStyle !== 'function') return undefined;
  const raw = getComputedStyle(element ?? document.documentElement).getPropertyValue(name).trim();
  if (name === '--bt-ease-constant' && raw === 'linear') return raw;
  const match = /^cubic-bezier\(\s*([+-]?(?:\d*\.)?\d+)\s*,\s*([+-]?(?:\d*\.)?\d+)\s*,\s*([+-]?(?:\d*\.)?\d+)\s*,\s*([+-]?(?:\d*\.)?\d+)\s*\)$/i.exec(raw);
  if (!match) return undefined;
  const values = match.slice(1).map(Number);
  return values.every(Number.isFinite) && values[0] >= 0 && values[0] <= 1 && values[2] >= 0 && values[2] <= 1 ? raw : undefined;
}
