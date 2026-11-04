import type { ReactNode } from 'react';
import { Info, Inbox, type LucideIcon } from 'lucide-react';
import { Skeleton } from './skeleton';

/** Creator Pipeline Home's CardHead/ToneIcon, shared across marketplace workspaces. */
export function CardHead({title,icon:Icon=Inbox,count}:{title:string;icon?:LucideIcon;count?:ReactNode}) {
  return <div className="buyer-card-head"><span className="buyer-tone-icon" aria-hidden="true"><Icon/></span><div className="buyer-card-titles"><h2>{title}{count!=null&&<span className="buyer-card-count">{count}</span>}</h2></div></div>;
}
/** Compact Calm card state (CP states/state-face, option A). */
export function SectionState({title,body,children,kind='empty',icon:Icon=Inbox}:{title:string;body?:ReactNode;children?:ReactNode;kind?:'empty'|'error'|'locked';icon?:LucideIcon}) {
  return <div className="buyer-section-state" data-kind={kind} role={kind==='error'?'alert':'status'}><span className="buyer-state-icon" aria-hidden="true"><Icon/></span><div className="buyer-state-text"><h2>{title}</h2>{body&&<p>{body}</p>}</div>{children&&<div className="buyer-state-actions">{children}</div>}</div>;
}
export function LoadingRows({label}:{label:string}) {
  return <div className="buyer-loading" role="status" aria-label={label}><span className="sr-only">{label}</span><Skeleton/><Skeleton/><Skeleton/></div>;
}
/** CP HeaderNotice: a calm icon and two-line fact, never an accent stripe. */
export function Notice({children}:{children:ReactNode}) {
  return <div className="hx-notice buyer-notice"><span className="hx-notice-icon"><Info aria-hidden="true"/></span><div className="hx-notice-copy">{children}</div></div>;
}
