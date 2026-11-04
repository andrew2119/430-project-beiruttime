import type { ComponentProps } from 'react';
import { cn } from './utils';
export function Card({ className, ...props }: ComponentProps<'section'>) {
  return <section className={cn('ui-card', className)} {...props}/>;
}
