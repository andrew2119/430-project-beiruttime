import Link from 'next/link';
import type { ComponentProps, ReactNode } from 'react';
import { CircleAlert, Inbox, LoaderCircle } from 'lucide-react';
import { cn } from './utils';
import { buttonVariants } from './button-variants';
export { Button } from './button';
export { buttonVariants } from './button-variants';
export { Card } from './card';
export { AuthCard } from './auth-card';
export { AutoHeight } from './auto-height';
export { RowSkeleton } from './row-skeleton';
export { Skeleton } from './skeleton';
export { Switch } from './switch';
export { CardHead, SectionState, LoadingRows, Notice } from './patterns';
export { Input } from './input';
export { Label } from './label';
export { Checkbox } from './checkbox';
export { Radio } from './radio';
export { Select } from './select';
export type { SelectOption, SelectProps } from './select';
export { StatusBadge, StatusBadge as Badge } from './badge';
export { Segmented, SegmentedGroup, SegmentedItem } from './segmented';
export { HeaderTabs } from './header-tabs';
export { FilterChips } from './filter-chips';
export { AnimatedList } from './animated-list';
export * from './dialog';
export * from './dropdown-menu';
export * from './popover';
export * from './sheet';
export { ImageFrame } from './image-frame';
export { LoadingOverlay } from './loading-overlay';
export { ScrollRegion } from './scroll-region';
export { ScrollBox } from './scroll-box';
export { Toaster, toast } from './toaster';
export { DirectionProvider } from './direction-provider';
export { useDialogExit } from './dialog-exit';

export function ButtonLink({ className, variant, size, chonk = false, children, ...props }: ComponentProps<typeof Link> & Parameters<typeof buttonVariants>[0] & { chonk?: boolean }) {
  const tone=variant ?? (className?.includes('button-secondary') ? 'outline' : 'default');
  const raised=chonk && size!=='icon';
  const plinth=tone==='destructive'?'pg-chonk-destructive':tone==='outline'||tone==='ghost'?'pg-chonk-neutral':'pg-chonk-primary';
  const classes=raised?cn('ui-chonk pg-chonk',plinth,size==='sm'&&'pg-chonk-sm',className):cn(buttonVariants({ variant:tone, size }),className);
  return <Link className={classes} {...props}>{raised?<span>{children}</span>:children}</Link>;
}
export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return <textarea className={cn('ui-textarea', className)} {...props} />;
}
/** Explicit translated copy, rather than a second language source in the UI package. */
export function State({ title, body, children, kind = 'empty' }: { title: string; body: string; children?: ReactNode; kind?: 'empty' | 'error' | 'loading' }) {
  const Icon=kind==='error'?CircleAlert:kind==='loading'?LoaderCircle:Inbox;
  return <div className="pg-face state" data-kind={kind} role={kind === 'loading' ? 'status' : undefined}><div className="pg-card pg-empty-card pg-face-card"><div className="pg-empty-icon" aria-hidden="true"><Icon className="size-6"/></div><h1 className="pg-empty-title">{title}</h1><div className="pg-face-copy">{body}</div>{children && <div className="pg-face-actions">{children}</div>}</div></div>;
}
export function BidiReference({ children }: { children: ReactNode }) { return <bdi dir="ltr">{children}</bdi>; }
