'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { Notice } from '@contracts/contracts-comms/inbox';
import { Button, ButtonLink, State } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { authenticatedRequest, refreshSession, signInHref, useSession } from '@/features/identity/session';
import { InboxContent, type NoticeAction } from './content';
import { inboxBase, inboxRead, noticePreferencesRead } from './reads';
import en from './en.json';
import ar from './ar.json';
import { InboxRecovery } from './recovery';
import './canonical.css';

function CurrentInbox({scope}:{scope:string}) {
  const locale=useLocale(),router=useRouter(),currentLocale=useRef(locale);
  useEffect(()=>{currentLocale.current=locale;},[locale]);
  const [cursors,setCursors]=useState<(string|null)[]>([null]);
  const inbox=usePageRead(inboxRead(scope,cursors[cursors.length-1])),preferences=usePageRead(noticePreferencesRead(scope));
  const [pending,setPending]=useState(false),[failed,setFailed]=useState(false),[refused,setRefused]=useState(false);
  const operationKeys=useRef(new Map<string,string>()),recovery=useRef(new InboxRecovery()),active=useRef(true);
  useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
  const refresh=async()=>{await inbox.refetch();await preferences.refetch();};
  const perform=async(action:()=>Promise<void>)=>{
    const operation=recovery.current;
    if(operation.busy||(operation.current&&operation.current!==action))return;
    setPending(true);setFailed(false);setRefused(false);
    const result=await operation.run(action);
    if(active.current){
      setFailed(result==='uncertain');setRefused(result==='refused');
      if(result==='confirmed'||result==='refused')await refresh();
      if(active.current)setPending(false);
    }
  };
  const command=async(path:string,body:unknown,identity:string,method='POST')=>{
    if(!operationKeys.current.has(identity))operationKeys.current.set(identity,crypto.randomUUID());
    await authenticatedRequest(path,{accessFingerprint:scope,method,headers:{'Content-Type':'application/json','Idempotency-Key':operationKeys.current.get(identity)!},body:JSON.stringify(body)});
  };
  const mark=(notice:Notice,action:NoticeAction)=>void perform(()=>command(`${inboxBase}/${notice.id}/${action}`,{expected_revision:notice.revision},`${notice.id}:${notice.revision}:${action}`));
  const preference=(enabled:boolean)=>{if(preferences.data){const revision=preferences.data.revision;void perform(()=>command(inboxBase+'/preferences',{optional_enabled:enabled,expected_revision:revision},`preferences:${revision}:${enabled}`,'PUT'));}};
  const open=(notice:Notice)=>void perform(async()=>{
    const result=await authenticatedRequest<{url:string}>(`${inboxBase}/${notice.id}/destination`,{accessFingerprint:scope});
    if(!/^\/(prices|buying|buyer|watches)(\/|\?|$)/.test(result.url))throw new Error('Destination unavailable');
    if(active.current)router.push(`/${currentLocale.current}${result.url}`);
  });
  const denied=[inbox.error,preferences.error].some(error=>error instanceof ApiError&&(error.status===401||error.status===403));
  return <InboxContent locale={locale} scope={scope} status={denied?'denied':inbox.isPending?'loading':inbox.isError||preferences.isError?'unavailable':'ready'} data={inbox.data} preferences={preferences.data} pending={pending} failed={failed} refused={refused} refreshing={inbox.isFetching||preferences.isFetching} hasPrevious={cursors.length>1} onRefresh={()=>void refresh()} onPrevious={()=>setCursors(current=>current.slice(0,-1))} onNext={cursor=>setCursors(current=>[...current,cursor])} onPreference={preference} onMark={mark} onOpen={open} onRetry={()=>{if(recovery.current.current)void perform(recovery.current.current);}}/>;
}

/** Uses the existing root cache and shell on the personal inbox route. */
export function CanonicalInboxPage() {
  const locale=useLocale(),copy=locale==='ar'?ar:en,session=useSession();
  const [restored,setRestored]=useState(false),[restoreFailed,setRestoreFailed]=useState(false);
  const restore=()=>{setRestoreFailed(false);void refreshSession().then(()=>setRestored(true)).catch(()=>{setRestored(true);setRestoreFailed(true);});};
  useEffect(()=>{let active=true;if(!session)void refreshSession().then(()=>{if(active)setRestored(true);}).catch(()=>{if(active){setRestored(true);setRestoreFailed(true);}});return()=>{active=false;};},[session]);
  return <PageFrame><PageHeader title={copy.inboxTitle} lead={copy.inboxIntro}/><PageBody>{session?<CurrentInbox key={session.access_fingerprint} scope={session.access_fingerprint}/>:restoreFailed?<State kind="error" title={copy.unavailable} body={copy.unavailableBody}><Button onClick={restore}>{copy.retry}</Button></State>:!restored?<State kind="loading" title={copy.loading} body={copy.loadingBody}/>:<State title={copy.signIn} body={copy.signInBody}><ButtonLink href={signInHref('/inbox',locale)}>{copy.signIn}</ButtonLink></State>}</PageBody></PageFrame>;
}
