import type { ReactNode } from 'react';
import { CircleAlert, Inbox, Clock3 } from 'lucide-react';
import { cn } from '../utils';

export function State({title, body, children, kind = 'empty', headingLevel = 2}: {title:string; body:string; children?:ReactNode; kind?:'empty'|'error'|'loading'; headingLevel?:2|3}) {
  const Icon = kind === 'error' ? CircleAlert : kind === 'loading' ? Clock3 : Inbox;
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  return <section className="bt-state" data-kind={kind} role={kind === 'error' ? 'alert' : kind === 'loading' ? 'status' : undefined} aria-busy={kind === 'loading' ? true : undefined}>
    <span className="bt-state-icon" aria-hidden="true"><Icon /></span>
    <div className="bt-state-copy"><Heading className="bt-heading">{title}</Heading><p className="bt-text">{body}</p></div>
    {children && <div className="bt-state-actions">{children}</div>}
  </section>;
}
export function Card({children, className}: {children:ReactNode; className?:string}) {return <div className={cn('bt-card', className)}>{children}</div>;}
export function Badge({children, tone = 'neutral'}: {children:ReactNode; tone?:'neutral'|'success'|'warning'|'error'}) {return <span className="bt-badge" data-tone={tone}>{children}</span>;}
export { Badge as StatusBadge };
export function Skeleton({size = 'text'}: {size?:'text'|'title'|'avatar'|'card'}) {return <span aria-hidden="true" className="bt-skeleton bt-placeholder" data-size={size}/>;}
export function RowSkeleton() {return <div className="bt-row-skeleton" aria-hidden="true"><Skeleton size="avatar"/><div className="bt-row-skeleton-copy"><Skeleton size="title"/><Skeleton/><Skeleton/></div></div>;}
