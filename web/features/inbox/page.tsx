'use client';
import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, Inbox } from 'lucide-react';
import { authenticatedRequest, useSession } from '@/features/identity/session';
import { AnimatedList, BidiReference, Button, Card } from '@beirut-time/ui';
import type { Inbox as InboxData, Notice } from '@contracts/contracts-comms/inbox';
import { command, Desk, Failure, PrivateGate, useCopy } from '../pricing/shared';
import { LoadingRows, Notice as NoticeLine, SectionState } from '@beirut-time/ui';
import { Switch } from '@beirut-time/ui';
import en from './en.json';
import ar from './ar.json';
const base='/api/web/v1/communications/v1/inbox';
function InboxView() {
  const {locale,t}=useCopy(),copy=locale==='ar'?ar:en,session=useSession()!,scope=session.access_fingerprint,client=useQueryClient(),router=useRouter();
  const operationKeys=useRef(new Map<string,string>()),[linkError,setLinkError]=useState<unknown>(null);
  const inbox=useInfiniteQuery({queryKey:['l07',scope,'inbox'],initialPageParam:null as string|null,queryFn:({pageParam,signal})=>authenticatedRequest<InboxData>(base+(pageParam?'?cursor='+pageParam:''),{signal}),getNextPageParam:last=>last.next_cursor,refetchInterval:15000,refetchIntervalInBackground:false});
  const preferences=useQuery({queryKey:['l07',scope,'notice-preferences'],queryFn:({signal})=>authenticatedRequest<{optional_enabled:boolean;revision:number}>(base+'/preferences',{signal})});
  const preference=useMutation({mutationFn:(enabled:boolean)=>authenticatedRequest(base+'/preferences',command({optional_enabled:enabled,expected_revision:preferences.data!.revision},crypto.randomUUID(),'PUT')),onSuccess:()=>void client.invalidateQueries({queryKey:['l07',scope,'notice-preferences']})});
  const marker=useMutation({mutationFn:({notice,action}:{notice:Notice;action:'read'|'clear'})=>{
    const operation=`${notice.id}:${notice.revision}:${action}`;if(!operationKeys.current.has(operation)) operationKeys.current.set(operation,crypto.randomUUID());
    return authenticatedRequest<Notice>(`${base}/${notice.id}/${action}`,command({expected_revision:notice.revision},operationKeys.current.get(operation)!));
  },onSuccess:()=>void client.invalidateQueries({queryKey:['l07',scope,'inbox']})});
  const open=async(notice:Notice)=>{setLinkError(null);try {const result=await authenticatedRequest<{url:string}>(`${base}/${notice.id}/destination`);if(!/^\/(prices|buying|buyer|watches)(\/|\?|$)/.test(result.url)) throw new Error('unavailable');router.push(`/${locale}${result.url}`);}catch(error){setLinkError(error);}};
  const notices=Array.from(new Map(inbox.data?.pages.flatMap(page=>page.items).map(notice=>[notice.id,notice])).values());
  return <>
    <Card className="l07-inbox-preferences"><div className="l07-inbox-pref"><div><label htmlFor="optional-notices">{copy.optionalNotices}</label><p className="l07-muted">{copy.preferencesInfo}</p></div><Switch id="optional-notices" label={copy.optionalNotices} checked={preferences.data?.optional_enabled??false} disabled={!preferences.data||preference.isPending} onChange={enabled=>preference.mutate(enabled)}/></div><Failure error={preferences.error||preference.error} retry={()=>void preferences.refetch()}/></Card>
    <div className="l07-actions l07-inbox-toolbar"><span className="l07-muted">{copy.unread}: <strong>{inbox.data?.pages[0].unread_count??'—'}</strong></span><Button chonk size="sm" variant="outline" onClick={()=>void inbox.refetch()} disabled={inbox.isFetching}>{copy.refreshInbox}</Button></div>
    <Failure error={inbox.error} retry={()=>void inbox.refetch()}/><Failure error={marker.error}/><Failure error={linkError}/>
    {inbox.isPending&&<LoadingRows label={t.loading}/>}
    <AnimatedList className="l07-inbox-list" items={notices} getKey={notice=>notice.id} empty={inbox.isSuccess?<Card><SectionState title={copy.emptyInbox} body={copy.emptyInboxBody} icon={Inbox}/></Card>:undefined}>
      {notice=><article className="l07-inbox-row" data-read={!!notice.read_at}>
        <span className="l07-inbox-icon" aria-hidden="true"><Bell/></span>
        <div className="l07-inbox-main"><p className="l07-muted">{notice.required?copy.required:t.optional} · {notice.read_at?copy.read:copy.unread}</p><h2>{copy[notice.kind]}</h2>
          {notice.sample&&<NoticeLine>{copy.sampleNotice}</NoticeLine>}
          <p className="l07-muted">{copy.eventTime}: <time dateTime={notice.event_time}>{new Date(notice.event_time).toLocaleString(locale==='ar'?'ar-LB':'en-GB',{timeZone:'Asia/Beirut'})}</time></p>
          <p className="l07-reference"><BidiReference>{notice.resource_id}</BidiReference>{notice.resource_revision!==null&&<> · {t.revision} {notice.resource_revision}</>}</p>
          <div className="l07-actions">{!notice.read_at&&<Button chonk size="sm" variant="outline" disabled={marker.isPending} onClick={()=>marker.mutate({notice,action:'read'})}>{copy.markRead}</Button>}<Button chonk size="sm" variant="outline" disabled={marker.isPending} onClick={()=>marker.mutate({notice,action:'clear'})}>{copy.clearNotice}</Button>{notice.destination?<Button chonk size="sm" onClick={()=>void open(notice)}>{copy.openRecord}</Button>:<p className="l07-muted">{copy.linkUnavailable}</p>}</div>
        </div><span className="l07-inbox-dot-slot">{!notice.read_at&&<span className="l07-inbox-dot" role="img" aria-label={copy.unread}/>}</span>
      </article>}
    </AnimatedList>
    {inbox.hasNextPage&&<Button chonk size="sm" variant="outline" disabled={inbox.isFetchingNextPage} onClick={()=>void inbox.fetchNextPage()}>{copy.loadMore}</Button>}
  </>;
}
export default function InboxPage() {const {locale}=useCopy(),copy=locale==='ar'?ar:en,session=useSession();return <Desk title={copy.inboxTitle} intro={copy.inboxIntro} current="inbox"><PrivateGate next="/inbox">{session&&<InboxView key={session.access_fingerprint}/>}</PrivateGate></Desk>;}
