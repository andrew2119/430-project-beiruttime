'use client';
import { useRef, type ReactNode } from 'react';
import { Search, type LucideIcon } from 'lucide-react';
import { Button } from '@beirut-time/ui';
import { cn } from '@/lib/utils';
import { StickyHeader } from './sticky-header';
import { TipBubble, useHeaderTips, useTitleFit } from './header-tips';
export { HeaderTabs } from '@beirut-time/ui';
export type HeaderAction = { id: string; label: string; icon: LucideIcon; primary?: boolean; disabled?: boolean; busy?: boolean; onSelect?: () => void; phoneLabel?: string };
export type PageHeaderProps = { title: ReactNode; count?: ReactNode; lead?: ReactNode; media?: ReactNode; tag?: ReactNode; actions?: HeaderAction[]; tools?: ReactNode; views?: ReactNode; nav?: ReactNode; status?: ReactNode; notice?: ReactNode; search?: { label: string; placeholder: string; value: string; onChange: (value: string) => void } };
/** Shared Calm card DOM and recipe. Domain queries and actions remain page-owned. */
export function PageHeader(p: PageHeaderProps) {
  const wrap=useRef<HTMLDivElement>(null);
  const tip=useHeaderTips(wrap);
  const row=useRef<HTMLDivElement>(null);
  const fit=useTitleFit(row);
  return <div ref={wrap} className="hx-wrap hx-sys hx-onpage"><TipBubble tip={tip}/><StickyHeader wrap={wrap}/><div className="hx-zone"><header className="hx-head" data-opt="A" data-nav={p.nav?'':undefined}>
    {p.lead && <div className="hx-lead">{p.lead}</div>}
    <div ref={row} className="hx-titlerow" data-media={p.media?'':undefined} data-fit={fit||undefined}><div className="hx-ident">{p.media && <div className="hx-media">{p.media}</div>}<div className="hx-tblock"><div className="hx-titleline"><h1 className="hx-title">{p.title}</h1>{p.tag}</div>{p.count!=null && <p className="hx-count">{p.count}</p>}</div></div><div className="hx-actions">{p.actions?.map(a=><Button key={a.id} type="button" chonk size="sm" variant={a.primary?'default':'outline'} className={`hx-act${a.primary?' hx-act-primary':''}`} aria-label={a.label} aria-busy={a.busy||undefined} disabled={a.disabled||a.busy} data-hx-tip={a.label} onClick={a.onSelect}><a.icon className={a.busy?'motion-safe:animate-spin':undefined} aria-hidden="true"/><span className={`hx-act-label${a.primary&&a.phoneLabel?' hx-act-label-desk':''}`}>{a.label}</span>{a.primary&&a.phoneLabel && <span className="hx-act-label hx-act-label-phone">{a.phoneLabel}</span>}</Button>)}</div></div>
    {p.views && <div className="hx-row hx-views-row"><div className="hx-scroll hx-group">{p.views}</div></div>}
    {(p.tools||p.search) && <div className="hx-row hx-tools-row">{p.search && <label className="hx-search"><Search aria-hidden="true"/><span className="sr-only">{p.search.label}</span><input type="search" className="pg-search-field" placeholder={p.search.placeholder} value={p.search.value} onChange={e=>p.search?.onChange(e.target.value)}/></label>}{p.tools}</div>}
    {p.nav && <div className="hx-navrow">{p.nav}</div>}
  </header>{p.status && <div className="hx-status">{p.status}</div>}{p.notice}</div></div>;
}
export function PageLayout({ children, className }: { children: ReactNode; className?: string }) { return <div className={cn('pg-list-page',className)}>{children}</div>; }
