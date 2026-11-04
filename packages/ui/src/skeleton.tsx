import type { ComponentProps } from 'react';
import { cn } from './utils';
/** Geometry-only placeholder, or the compatible announced page composition. */
export function Skeleton({ label, className, ...props }: ComponentProps<'div'> & { label?: string }) {
  if (!label) return <div aria-hidden="true" className={cn('pg-skeleton ui-skeleton', className)} {...props}/>;
  return <div className={cn('skeleton-page', className)} role="status" aria-label={label} {...props}>
    <div className="pg-skeleton skeleton-title"/><div className="pg-skeleton skeleton-body"/><div className="pg-skeleton skeleton-card"/><span className="sr-only">{label}</span>
  </div>;
}
