'use client';
import type { ReactNode } from 'react';
/** Same CP CSS-owned loader phases; hidden warm content is never announced. */
export function LoadingOverlay({ phase, label, children }: { phase: 'hidden' | 'open' | 'closing'; label: string; children: ReactNode }) {
  const active = phase !== 'hidden';
  return <div role={active ? 'status' : undefined} aria-label={active ? label : undefined} aria-busy={active || undefined} aria-hidden={!active || undefined} data-loader-phase={phase} className="pg-loading-overlay fixed inset-0 z-(--z-loading-overlay) bg-background">{children}</div>;
}
