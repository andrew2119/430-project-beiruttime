'use client';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Badge, Button, ButtonLink, Card, Checkbox, Input, RowSkeleton, Segmented, Select, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame as PageLayout, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { refreshSession, useSession, useSessionState } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { usePageRead } from '@/lib/page-speed/read';
import type { Command, Notice, Receipt, SavedSearch } from '@contracts/contracts-comms/saved-searches';
import { destination, lookup, mutateNotice, noticesRead, searchesRead, sendCommand } from './api';
import { emptyDraft, fromQuery, fromSaved, makeCommand, searchHref, type Draft } from './state';
import { en, ar } from './copy';
import { SignIn } from './sign-in';
import { holdPublicDraft, clearPublicDraft, takePublicDraft } from './intent';
import './styles.css';

function accessDenied(error:unknown) {return error instanceof ApiError&&(error.status===401||error.status===403);}

export default function SavedSearchView() {
  const locale=useLocale(),t=locale==='ar'?ar:en,params=useSearchParams(),access=useAccessContext();
  const [draft,setDraft]=useState<Draft>(()=>takePublicDraft(access.fingerprint)??fromQuery(new URLSearchParams(params.toString())));
  const [partition,setPartition]=useState(access.fingerprint);
  // A public draft can resume after sign-in; a prior private identity cannot carry over.
  if(partition!==access.fingerprint){setPartition(access.fingerprint);if(partition){clearPublicDraft();setDraft({...emptyDraft});}else{const resumed=takePublicDraft(access.fingerprint);if(resumed)setDraft(resumed);}}
  return <PageLayout><PageHeader title={t.title} lead={t.intro}/><PageBody><Workspace key={access.fingerprint??'public'} fingerprint={access.fingerprint} draft={draft} setDraft={setDraft}/></PageBody></PageLayout>;
}
export function Workspace({fingerprint,draft,setDraft}:{fingerprint:string|null;draft:Draft;setDraft:(draft:Draft)=>void}) {
  const locale=useLocale(),t=locale==='ar'?ar:en,session=useSession(),sessionState=useSessionState(),router=useRouter();
  const currentLocale=useRef(locale);
  useLayoutEffect(()=>{currentLocale.current=locale;},[locale]);
  const [tab,setTab]=useState('searches'),[offset,setOffset]=useState(0),[noticeOffset,setNoticeOffset]=useState(0);
  const allowed=!!fingerprint&&session?.principal.roles.includes('buyer');
  const searches=usePageRead(allowed?searchesRead(fingerprint!,offset):null),notices=usePageRead(allowed?noticesRead(fingerprint!,noticeOffset):null);
  const [status,setStatus]=useState<keyof typeof en|null>(null),[attempt,setAttempt]=useState<Command|null>(null),[pending,setPending]=useState(false);
  const busy=useRef(false),alive=useRef(true),controllers=useRef(new Set<AbortController>());
  useEffect(()=>{alive.current=true;const active=controllers.current;return()=>{alive.current=false;active.forEach(c=>c.abort());};},[]);
  const messages={placeholder:t.selectPlaceholder,filter:t.selectFilter,emptyTitle:t.selectEmpty,emptyBody:t.selectEmptyBody,close:t.close,loading:t.selectLoading,errorTitle:t.selectError,errorBody:t.selectErrorBody,retry:t.retry};
  const change=(patch:Partial<Draft>)=>setDraft({...draft,...patch});
  function review(row:SavedSearch){if(busy.current||attempt)return;setDraft(fromSaved(row));setStatus(null);}
  async function act(kind:Command['kind']='save',recover=false){
    if(!fingerprint||busy.current)return;
    let body=attempt;
    if(!body){try{body=makeCommand(draft,kind);}catch{setStatus('invalid');return;}setAttempt(body);}
    const immutable=body;busy.current=true;setPending(true);setStatus(null);
    const controller=new AbortController();controllers.current.add(controller);
    try{
      let receipt:Receipt;
      if(recover){try{receipt=await lookup(immutable.operation_id,fingerprint,controller.signal);}catch(error){if(!(error instanceof ApiError)||error.status!==404)throw error;receipt=await sendCommand(immutable,fingerprint,controller.signal);}}
      else receipt=await sendCommand(immutable,fingerprint,controller.signal);
      if(receipt.operation_id!==immutable.operation_id||receipt.subject_id!==immutable.subject_id||receipt.expected_revision!==immutable.expected_revision||receipt.result.id!==immutable.subject_id)throw new Error('unavailable');
      if(!alive.current)return;
      setDraft(receipt.state==='removed'?{...emptyDraft}:fromSaved(receipt.result));setAttempt(null);setStatus(receipt.state==='removed'?'removed':'saved');void searches.refetch();
    }catch(error){if(!alive.current)return;
      if(error instanceof ApiError&&error.status>=400&&error.status<500){setAttempt(null);setStatus(error.status===401||error.status===403?'denied':error.code==='stale_revision'?'stale':error.code==='subscription_limit'?'limit':'invalid');}
      else setStatus('pending');
    }finally{controllers.current.delete(controller);busy.current=false;if(alive.current)setPending(false);}
  }
  const [noticeAttempt,setNoticeAttempt]=useState<{row:Notice;kind:'read'|'clear'|'open'}|null>(null);
  async function noticeAction(row:Notice,kind:'read'|'clear'|'open'){
    if(!fingerprint||busy.current)return;busy.current=true;setPending(true);setStatus(null);setNoticeAttempt({row,kind});
    const controller=new AbortController();controllers.current.add(controller);
    try{
      if(kind==='open'){const result=await destination(row.id,fingerprint,controller.signal);if(!/^\/watches\/[0-9a-f-]{36}$/i.test(result.href))throw new Error('unavailable');if(alive.current)router.push(`/${currentLocale.current}${result.href}`);}
      else await mutateNotice(row.id,kind,row.revision,fingerprint,controller.signal);
      if(alive.current){setNoticeAttempt(null);setStatus('done');void notices.refetch();}
    }catch(error){if(alive.current){setStatus(accessDenied(error)?'denied':error instanceof ApiError&&error.status===404?'missing':'noticeError');if(error instanceof ApiError&&error.status<500){setNoticeAttempt(null);void notices.refetch();}}}
    finally{controllers.current.delete(controller);busy.current=false;if(alive.current)setPending(false);}
  }
  const locked=pending||!!attempt||!!noticeAttempt;
  const list=tab==='searches'?searches:notices;
  const denied=accessDenied(list.error);
  const recovery=<ButtonLink href={`/${locale}/account`} variant="outline">{t.recoverAccess}</ButtonLink>;
  return <div className="saved-search-stack">
    {draft.importInvalid&&<State kind="error" title={t.invalid} body={t.importInvalid}><bdi>{draft.importedCurrency}</bdi></State>}
    <Card><form className="saved-search-form" aria-busy={pending} onSubmit={event=>{event.preventDefault();if(!attempt&&status!=='stale')void act();}}>
      <Input label={t.name} value={draft.name} onValueChange={value=>change({name:value})} disabled={locked} required/>
      <div className="saved-search-grid">{(['q','brand','model','location'] as const).map(field=><Input key={field} label={t[field]} value={draft[field]} onValueChange={value=>change({[field]:value})} disabled={locked}/>)}
        <Input label={t.minimum} hint={t.money} inputMode="decimal" value={draft.minimum} onValueChange={minimum=>change({minimum})} disabled={locked}/>
        <Input label={t.maximum} hint={t.money} inputMode="decimal" value={draft.maximum} onValueChange={maximum=>change({maximum})} disabled={locked}/>
        <Select label={t.mode} value={draft.sale_mode} onValueChange={value=>change({sale_mode:value as Draft['sale_mode']})} disabled={locked} messages={messages} options={(['','fixed','auction','offer'] as const).map(value=>({value,label:value?t[value]:t.any}))}/>
        <Select label={t.sort} value={draft.sort} onValueChange={value=>change({sort:value as Draft['sort']})} disabled={locked} messages={messages} options={(['newest','price_asc','price_desc','ending_soon'] as const).map(value=>({value,label:t[value]}))}/>
      </div>
      <Checkbox label={t.alerts} checked={draft.alerts} onCheckedChange={alerts=>change({alerts})} disabled={locked}/>
      <div className="saved-search-actions"><Button type="submit" disabled={!allowed||locked||status==='stale'||draft.importInvalid}>{pending?t.sending:t.save}</Button>
        {draft.id&&<Button type="button" variant="outline" disabled={!allowed||locked||status==='stale'||draft.importInvalid} onClick={()=>void act('remove')}>{t.remove}</Button>}
        <Button type="button" variant="outline" disabled={locked} onClick={()=>{setDraft({...emptyDraft});setStatus(null);}}>{t.newSearch}</Button>
      </div>
    </form></Card>
    {!session&&<div className="saved-search-stack">{sessionState==='restoring'?<p role="status">{t.authLoading}</p>:<><p role="status">{sessionState==='unavailable'?t.authUnavailable:t.signin}</p>{sessionState==='unavailable'&&<Button type="button" onClick={()=>void refreshSession().catch(()=>setStatus('unavailable'))}>{t.retry}</Button>}<SignIn label={t.signin} onIntent={()=>holdPublicDraft(draft)} onCancel={clearPublicDraft}/></>}</div>}
    {session&&!allowed&&<State kind="error" title={t.denied} body={t.denied}/>}
    {status==='denied'&&recovery}
    {status&&<div role={['saved','removed','done'].includes(status)?'status':'alert'} className="saved-search-feedback"><p>{t[status]}</p>{attempt&&<><bdi>{attempt.operation_id}</bdi><Button disabled={pending} onClick={()=>void act(attempt.kind,true)}>{t.check}</Button></>}{noticeAttempt&&<Button disabled={pending} onClick={()=>void noticeAction(noticeAttempt.row,noticeAttempt.kind)}>{t.retry}</Button>}{status==='noticeError'&&<Button disabled={pending} onClick={()=>{void notices.refetch();setStatus(null);}}>{t.reload}</Button>}{status==='stale'&&<Button disabled={pending} onClick={()=>void searches.refetch()}>{t.reload}</Button>}</div>}
    {allowed&&<>
      <Segmented label={t.title} value={tab} onValueChange={setTab} options={[{value:'searches',label:t.searches},{value:'notices',label:t.notices}]}/>
      {list.isPending?<div role="status" aria-label={t.loading}><RowSkeleton/><RowSkeleton/></div>:list.isError?<State kind="error" title={denied?t.denied:t.unavailable} body={denied?t.accessRecovery:t.retry}>{denied?recovery:<Button onClick={()=>void list.refetch()}>{t.retry}</Button>}</State>:<AnswerArrival view={`saved-searches:${tab}`}>
        <p className="bt-number">{t.total}: {formatNumber(list.data?.total??0,locale)}</p>
        {tab==='searches'?(searches.data?.items.length?searches.data.items.map(row=><Card key={row.id}><div className="saved-search-stack"><h2 className="bt-heading">{row.name}</h2><Badge>{row.alerts_enabled?t.enabled:t.disabled}</Badge><p>{row.criteria.q} {row.criteria.brand} {row.criteria.model} {row.criteria.location}</p><div className="saved-search-actions"><Button disabled={locked} onClick={()=>review(row)}>{t.edit}</Button><ButtonLink href={`/${locale}${searchHref(row.criteria)}`} variant="outline">{t.browse}</ButtonLink></div></div></Card>):<State title={t.empty} body={t.emptyBody}/>):(notices.data?.items.length?notices.data.items.map(row=><Card key={row.id}><div className="saved-search-stack"><h2 className="bt-heading">{t.notified}</h2><Badge>{row.read?t.readState:t.unread}</Badge>{row.sample&&<p>{t.sample}</p>}<bdi>{row.listing_id}</bdi><time dateTime={row.event_time}>{new Intl.DateTimeFormat(locale==='ar'?'ar-LB-u-nu-arab':'en-US-u-nu-latn',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(row.event_time))}</time><div className="saved-search-actions"><Button disabled={locked} onClick={()=>void noticeAction(row,'open')}>{t.open}</Button><Button variant="outline" disabled={locked||row.read} onClick={()=>void noticeAction(row,'read')}>{t.read}</Button><Button variant="outline" disabled={locked} onClick={()=>void noticeAction(row,'clear')}>{t.clear}</Button></div></div></Card>):<State title={t.noNotices} body={t.noNoticesBody}/>)}
        <div className="saved-search-actions"><Button variant="outline" disabled={locked||(list.data?.offset??0)===0} onClick={()=>tab==='searches'?setOffset(Math.max(0,offset-20)):setNoticeOffset(Math.max(0,noticeOffset-20))}>{t.previous}</Button><Button variant="outline" disabled={locked||!list.data||list.data.offset+list.data.limit>=list.data.total} onClick={()=>tab==='searches'?setOffset(offset+20):setNoticeOffset(noticeOffset+20)}>{t.next}</Button></div>
      </AnswerArrival>}
    </>}
  </div>;
}
