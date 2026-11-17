'use client';
import type { Inbox, Notice } from '@contracts/contracts-comms/inbox';
import type { Locale } from '@beirut-time/i18n';
import { AnimatedList, Badge, Button, Card, formatNumber, RowSkeleton, State, Switch } from '@beirut-time/ui/foundation';
import type { NoticePreferences } from './reads';
import en from './en.json';
import ar from './ar.json';
export type InboxStatus = 'loading'|'ready'|'denied'|'unavailable';
export type NoticeAction = 'read'|'clear';
export type InboxContentProps = {
  locale:Locale;scope:string;status:InboxStatus;data?:Inbox;preferences?:NoticePreferences;
  pending:boolean;failed:boolean;refused?:boolean;refreshing:boolean;hasPrevious:boolean;
  onRefresh:()=>void;onPrevious:()=>void;onNext:(cursor:string)=>void;
  onPreference:(enabled:boolean)=>void;onMark:(notice:Notice,action:NoticeAction)=>void;onOpen:(notice:Notice)=>void;
  onRetry:()=>void;
};
export function InboxContent({locale,scope,status,data,preferences,pending,failed,refused,refreshing,hasPrevious,onRefresh,onPrevious,onNext,onPreference,onMark,onOpen,onRetry}:InboxContentProps) {
  const copy=locale==='ar'?ar:en;
  const blocked=pending||failed;
  if(status==='denied') return <State kind="error" title={copy.accessDenied} body={copy.accessDeniedBody}><Button onClick={onRefresh}>{copy.retry}</Button></State>;
  if(status==='loading'&&!data) return <div role="status" aria-label={copy.loading} aria-busy="true"><RowSkeleton/><RowSkeleton/><RowSkeleton/></div>;
  return <div className="l22-inbox">
    <Card><Switch label={copy.optionalNotices} hint={copy.preferencesInfo} checked={preferences?.optional_enabled??false} disabled={!preferences||blocked} onCheckedChange={onPreference}/></Card>
    {status==='unavailable'&&<State kind="error" title={copy.unavailable} body={copy.unavailableBody}><Button onClick={onRefresh}>{copy.retry}</Button></State>}
    {refused&&<State kind="error" title={copy.actionRefused} body={copy.actionRefusedBody}><Button onClick={onRefresh}>{copy.refreshInbox}</Button></State>}
    {failed&&<State kind="error" title={copy.actionUncertain} body={copy.actionUncertainBody}><Button disabled={pending} onClick={onRetry}>{copy.retrySameAction}</Button></State>}
    {pending&&<p role="status" className="bt-text">{copy.pending}</p>}
    <div className="l22-inbox-actions"><p className="bt-text">{copy.total}: <span className="bt-number">{formatNumber(data?.total_count,locale)}</span> · {copy.unread}: <span className="bt-number">{formatNumber(data?.unread_count,locale)}</span></p><Button variant="outline" busy={refreshing} onClick={onRefresh}>{copy.refreshInbox}</Button></div>
    {data&&<AnimatedList scopeKey={scope} items={data.items} getKey={notice=>notice.id} empty={<Card><State title={copy.emptyInbox} body={copy.emptyInboxBody}/></Card>}>
      {notice=><Card><article className="l22-inbox-notice">
        <div className="l22-inbox-actions"><Badge>{notice.required?copy.required:copy.optional}</Badge><span className="bt-text">{notice.read_at?copy.read:copy.unread}</span></div>
        <h2 className="bt-heading">{copy[notice.kind]}</h2>
        {notice.sample&&<p className="bt-text">{copy.sampleNotice}</p>}
        <p className="bt-text">{copy.eventTime}: <time dateTime={notice.event_time}>{new Date(notice.event_time).toLocaleString(locale==='ar'?'ar-LB':'en-GB',{timeZone:'Asia/Beirut'})}</time></p>
        <p className="bt-text"><bdi dir="ltr">{notice.resource_id}</bdi>{notice.resource_revision!==null&&<> · {copy.revision} <span className="bt-number">{formatNumber(notice.resource_revision,locale)}</span></>}</p>
        <div className="l22-inbox-actions">{!notice.read_at&&<Button variant="outline" disabled={blocked} onClick={()=>onMark(notice,'read')}>{copy.markRead}</Button>}<Button variant="outline" disabled={blocked} onClick={()=>onMark(notice,'clear')}>{copy.clearNotice}</Button>{notice.destination?<Button disabled={blocked} onClick={()=>onOpen(notice)}>{copy.openRecord}</Button>:<p className="bt-text">{copy.linkUnavailable}</p>}</div>
      </article></Card>}
    </AnimatedList>}
    <nav className="l22-inbox-actions" aria-label={copy.pages}><Button variant="outline" disabled={!hasPrevious||blocked||refreshing} onClick={onPrevious}>{copy.previousPage}</Button><Button variant="outline" disabled={!data?.next_cursor||blocked||refreshing} onClick={()=>{if(data?.next_cursor)onNext(data.next_cursor);}}>{copy.loadMore}</Button></nav>
  </div>;
}
