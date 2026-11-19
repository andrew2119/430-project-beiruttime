'use client';
import { useRef, type ReactNode } from 'react';
import { StickyHeader } from '../sticky-header';
import { TipBubble, useHeaderTips, useTitleFit } from '../header-tips';
export { HeaderTabs } from '@beirut-time/ui';
import { RowSkeleton, Skeleton } from '@beirut-time/ui/foundation';

/** One header geometry for real pages, first answers and the starting template. */
export function PageHeader({title,lead,count,actions,tools,tabs,notice}: {title:string;lead?:string;count?:ReactNode;actions?:ReactNode;tools?:ReactNode;tabs?:ReactNode;notice?:ReactNode}) {
  const wrap = useRef<HTMLDivElement>(null), row = useRef<HTMLDivElement>(null);
  const tip = useHeaderTips(wrap), fit = useTitleFit(row);
  return <div ref={wrap} className="bt-page-header hx-wrap hx-sys hx-onpage"><TipBubble tip={tip}/><StickyHeader wrap={wrap}/><div className="hx-zone">
    <header className="hx-head" data-opt="A" data-nav={tabs ? '' : undefined}>
      {lead && <div className="hx-lead">{lead}</div>}
      <div ref={row} className="hx-titlerow" data-fit={fit || undefined}>
        <div className="hx-ident"><div className="hx-tblock"><div className="hx-titleline"><h1 id="page-title" className="hx-title">{title}</h1></div>{count != null && <p className="hx-count bt-number">{count}</p>}</div></div>
        <div className="hx-actions">{actions}</div>
      </div>
      {tools && <div className="hx-row hx-tools-row">{tools}</div>}
      {tabs && <div className="hx-navrow" data-bt-glance="">{tabs}</div>}
    </header>{notice}
  </div></div>;
}
export function PageFrame({children}: {children:ReactNode}) { return <section className="bt-page" aria-labelledby="page-title">{children}</section>; }
export function PageBody({children}: {children:ReactNode}) { return <div className="bt-page-body">{children}</div>; }
/** Shared shapes reserve the same title/body slots, never a blank replacement. */
export function PageLoading({label}: {label:string}) {
  return <section className="bt-page bt-page-wait" role="status" aria-label={label} aria-busy="true"><div className="bt-page-header"><Skeleton size="title"/><Skeleton/></div><div className="bt-page-body"><RowSkeleton/><RowSkeleton/><RowSkeleton/></div></section>;
}
