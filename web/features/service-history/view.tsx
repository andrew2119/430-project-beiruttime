'use client';
import { useEffect, useRef, useReducer } from 'react';
import { Button, Card, Checkbox, Input, RowSkeleton, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageHeader, PageFrame } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { useSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { historyRead, validSelection, type Selection } from './read';
import { publishSelection, type PublicationAttempt, type PublicationResult } from './publication';
import { historyReducer, initialHistoryState } from './model';
import en from './en.json';
import ar from './ar.json';
import './styles.css';

export default function History() {
  useSession();
  const access=useAccessContext();
  return <HistoryContent key={access.fingerprint ?? 'signed-out'} fingerprint={access.fingerprint ?? ''}/>;
}
function HistoryContent({fingerprint}:{fingerprint:string}) {
  const locale=useLocale(), t=locale==='ar'?ar:en;
  const [{watch,revision,selection,invalid,selected,publication},dispatch]=useReducer(historyReducer,initialHistoryState);
  const setWatch=(watch:string)=>dispatch({type:'patch',patch:{watch}});
  const setRevision=(revision:string)=>dispatch({type:'patch',patch:{revision}});
  const setSelection=(selection:Selection|null)=>dispatch({type:'patch',patch:{selection}});
  const setInvalid=(invalid:boolean)=>dispatch({type:'patch',patch:{invalid}});
  const setSelected=(value:string[]|((previous:string[])=>string[]))=>typeof value==='function'?dispatch({type:'selected',update:value}):dispatch({type:'patch',patch:{selected:value}});
  const setPublication=(publication:PublicationResult|null)=>dispatch({type:'patch',patch:{publication}});
  const attempt=useRef<PublicationAttempt|null>(null), active=useRef<AbortController|null>(null);
  useEffect(()=>()=>active.current?.abort(),[]);
  const publish=async()=>{
    if(!selection||active.current)return;
    if(!attempt.current)attempt.current={operation_id:crypto.randomUUID(),expected_revision:selection.revision,job_ids:[...selected],watch:selection.watch};
    const controller=new AbortController();active.current=controller;
    const operation_id=attempt.current.operation_id;
    setPublication({state:'pending',operation_id});
    try {
      const response=await publishSelection(fingerprint,attempt.current,controller.signal);
      if(controller.signal.aborted)return;
      setPublication(response);
      if(response.state!=='pending')attempt.current=null;
    } catch(error) {if(!controller.signal.aborted){const state=error instanceof ApiError&&[401,403].includes(error.status)?'denied':'pending';setPublication({state,operation_id});if(state==='denied')attempt.current=null;}}
    finally {if(active.current===controller)active.current=null;}
  };
  const locked=publication?.state==='pending';
  const result=usePageRead(fingerprint&&selection?historyRead(fingerprint,selection):null);
  const data=result.isError?undefined:result.data;
  const state=!fingerprint?'denied':result.isError?(result.error instanceof ApiError&&[401,403].includes(result.error.status)?'denied':'unavailable'):data?.state;
  const move=(page:number, rev=selection?.revision??0)=>{if(selection&&!locked)setSelection({...selection,page,revision:rev,operation:crypto.randomUUID()});};
  const date=(value:string)=>new Intl.DateTimeFormat(locale==='ar'?'ar-LB-u-nu-arab':'en-US-u-nu-latn',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(value))+' UTC';
  return <PageFrame><PageHeader title={t.title} count={t.intro}/>
    <form className="history-form" onSubmit={event=>{event.preventDefault();if(locked)return;const valid=validSelection(watch,revision);setInvalid(!valid);if(valid){setSelected([]);setPublication(null);setSelection({watch,revision:Number(revision),page:0,operation:crypto.randomUUID()});}}}>
      <Input label={t.watch} value={watch} onValueChange={setWatch} required/>
      <Input label={t.revision} inputMode="numeric" value={revision} onValueChange={setRevision} required/>
      <Button type="submit" disabled={!fingerprint||locked}>{t.open}</Button>
    </form>
    {invalid&&<p role="alert">{t.invalid}</p>}
    {selection&&<p className="history-reference">{t.reference}: <bdi>{selection.operation}</bdi></p>}
    {selection&&result.isPending&&fingerprint&&<><State kind="loading" title={t.title} body={t.loading}/><RowSkeleton/></>}
    {state&&state!=='ready'&&<State kind={state==='pending'?'loading':'error'} title={t.title} body={t[state]}>
      {state==='stale'&&data?<Button onClick={()=>{setRevision(String(data.revision));move(0,data.revision);}}>{t.current}</Button>:state!=='denied'&&<Button onClick={()=>void result.refetch()}>{t.retry}</Button>}
      <a href={`/${locale}/account`}>{t.account}</a>
      <a href={`/${locale}/inbox`}>{t.support}</a>
    </State>}
    {publication&&<State kind={locked?'loading':publication.state==='ready'?'empty':'error'} title={t.publish} body={publication.state==='ready'?t.published:locked?t.publishing:t[publication.state]}><bdi>{publication.operation_id}</bdi><a href={`/${locale}/inbox`}>{t.support}</a>{locked&&<Button onClick={()=>void publish()}>{t.retry}</Button>}</State>}
    {data?.state==='ready'&&<section aria-label={t.title}>
      <p>{t.total}: {formatNumber(data.total,locale)}</p>
      {data.total===0&&<State title={t.title} body={t.empty}/>}
      {data.items.map(entry=><Card key={entry.job_id} className="history-record">
        <Checkbox label={t.select} checked={selected.includes(entry.job_id)} disabled={locked||(!selected.includes(entry.job_id)&&selected.length>=50)} onCheckedChange={checked=>setSelected(previous=>checked?[...previous,entry.job_id]:previous.filter(id=>id!==entry.job_id))}/>
        <h2>{t[entry.kind]}</h2><p><bdi>{entry.job_id}</bdi></p><p>{date(entry.released_at)}</p>
        <ul>{entry.work_codes.map((code,index)=><li key={`${code}:${index}`}>{t[code]}</li>)}</ul>
        <h3>{t.warranty}</h3>{entry.warranty?<><p>{t.issuer}: <bdi>{entry.warranty.issuer_id}</bdi></p><p>{t[entry.warranty.scope_code]}</p><p>{t.start}: {date(entry.warranty.starts_at)}</p><p>{t.terms}: {formatNumber(entry.warranty.terms_revision,locale)}</p><p dir="auto">{locale==='ar'?entry.warranty.terms_ar:entry.warranty.terms_en}</p></>:<p>{t.absent}</p>}
        <p>{t.aftercare}</p>
      </Card>)}
      <p>{t.withdraw}</p><p>{t.selected}: {formatNumber(selected.length,locale)}</p>
      <Button onClick={()=>void publish()}>{locked?t.retry:t.publish}</Button>

      <nav className="history-pagination" aria-label={t.title}><Button disabled={data.page===0} onClick={()=>move(data.page-1)}>{t.previous}</Button><Button disabled={(data.page+1)*data.page_size>=data.total} onClick={()=>move(data.page+1)}>{t.next}</Button></nav>
    </section>}
  </PageFrame>;
}
