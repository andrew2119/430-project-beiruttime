import type { ReactNode } from 'react';
import { RowSkeleton, Skeleton } from '@beirut-time/ui/foundation';

/** One header geometry for real pages, first answers and the starting template. */
export function PageHeader({title,lead,count,actions,tools,tabs,notice}: {title:string;lead?:string;count?:ReactNode;actions?:ReactNode;tools?:ReactNode;tabs?:ReactNode;notice?:ReactNode}) {
  return <header className="bt-page-header">
    <div className="bt-page-title-row"><div className="bt-page-heading"><h1 id="page-title" className="bt-display">{title}</h1>{count != null && <p className="bt-page-count bt-number">{count}</p>}{lead && <p className="bt-text">{lead}</p>}</div>{actions && <div className="bt-page-actions">{actions}</div>}</div>
    {tools && <div className="bt-page-tools">{tools}</div>}{tabs && <div className="bt-page-tabs" data-bt-glance="">{tabs}</div>}{notice && <div className="bt-page-notice">{notice}</div>}
  </header>;
}
export function PageFrame({children}: {children:ReactNode}) { return <section className="bt-page" aria-labelledby="page-title">{children}</section>; }
export function PageBody({children}: {children:ReactNode}) { return <div className="bt-page-body">{children}</div>; }
/** Shared shapes reserve the same title/body slots, never a blank replacement. */
export function PageLoading({label}: {label:string}) {
  return <section className="bt-page bt-page-wait" role="status" aria-label={label} aria-busy="true"><div className="bt-page-header"><Skeleton size="title"/><Skeleton/></div><div className="bt-page-body"><RowSkeleton/><RowSkeleton/><RowSkeleton/></div></section>;
}
