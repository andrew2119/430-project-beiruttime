'use client';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button, ButtonLink, Card, Checkbox, Input, State, Textarea, formatAmount } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { useSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import type { CleaningCommand, CleaningResult } from '@contracts/contracts-service/cleaning/v1';
import { cleaningRead, lookupCleaning, sendCleaning } from './api';
import { copy } from './copy';
const dollars = (cents:number)=>`${Math.floor(cents/100)}.${String(cents%100).padStart(2,'0')}`;
const validId = (value:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);

export default function Cleaning() {
  useSession();
  const access = useAccessContext();
  return <CleaningScope key={access.fingerprint??''} access={access.fingerprint??''}/>;
}
function CleaningScope({access}:{access:string}) {
  const locale = useLocale(), t = copy[locale];
  const [switchLocked,setSwitchLocked] = useState(false);
  const switchLock = useRef(false);
  function lockSwitch(value:boolean) {switchLock.current=value;setSwitchLocked(value);}
  const params = useSearchParams();
  const [reference,setReference] = useState(params.get('request')??'');
  const [subject,setSubject] = useState(validId(reference)?reference:'');
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    <form onSubmit={event=>{event.preventDefault();if(!switchLock.current&&validId(reference)) setSubject(reference);}}>
      <Input label={t.subject} value={reference} onValueChange={setReference} disabled={switchLocked} required/>
      <Button type="submit" disabled={switchLocked||!validId(reference)}>{t.open}</Button>
    </form>
    {!access?<State title={t.title} body={t.signedOut}/>:!subject?<State title={t.title} body={t.missing}/>:<RequestForm key={subject} subject={subject} access={access} lockSwitch={lockSwitch}/>}
  </PageBody></PageFrame>;
}
function RequestForm({subject,access,lockSwitch}:{subject:string;access:string;lockSwitch:(value:boolean)=>void}) {
  const locale=useLocale(), t=copy[locale];
  const read=usePageRead(cleaningRead(subject,access));
  const [condition,setCondition]=useState(''), [limits,setLimits]=useState('');
  const [caseArea,setCase]=useState(true), [bracelet,setBracelet]=useState(false);
  const [permission,setPermission]=useState(false), [water,setWater]=useState(false), [movement,setMovement]=useState(false), [terms,setTerms]=useState('');
  const [pending,setPending]=useState<CleaningCommand|null>(null), [busy,setBusy]=useState(false);
  const [error,setError]=useState(''), [result,setResult]=useState<CleaningResult|null>(null);
  const active=useRef<AbortController|null>(null);
  useEffect(()=>()=>active.current?.abort(),[]);
  const record=result??read.data?.record, quote=record?.state==='accepted'?record.quote:read.data?.quote;
  const quoteKey=quote?`${quote.quote_id}:${quote.quote_revision}:${quote.terms_revision}:${quote.request_revision}`:'';
  const locked=Boolean(pending)||busy||record?.state==='accepted';
  function message(error:unknown) {
    if(error instanceof ApiError) {
      if(error.status===401||error.status===403) return 'denied';
      if(error.status===409) return 'stale';
      if(error.status===503) return 'unavailable';
    }
    return 'error';
  }
  async function perform(command:CleaningCommand, recover=false) {
    const controller=new AbortController();active.current=controller;setBusy(true);setError('');
    try {
      const prior=recover?await lookupCleaning(command,access,controller.signal):null;
      const answer=prior?.result??await sendCleaning(command,access,controller.signal);
      if(controller.signal.aborted) return;
      setResult(answer);setPending(null);lockSwitch(false);setTerms('');void read.refetch();
    } catch(cause) {
      if(controller.signal.aborted) return;
      const kind=message(cause);setError(kind);
      if(kind==='denied'||kind==='stale') {setPending(null);lockSwitch(false);}
    } finally {if(!controller.signal.aborted) setBusy(false);}
  }
  function submit(action:'request'|'accept') {
    if(!read.data||pending||busy) return;
    const command:CleaningCommand={...read.data.binding,operation_id:crypto.randomUUID(),expected_revision:record?.revision??0,
      action,areas:action==='accept'?record!.areas:[...(caseArea?['case' as const]:[]),...(bracelet?['bracelet' as const]:[])],
      condition:action==='accept'?record!.condition:condition,preservation_limits:action==='accept'?record!.preservation_limits:limits,
      assessment_permission:true,no_submersion_promise:true,no_movement_service:true,
      quote_id:action==='accept'?quote!.quote_id:null,quote_revision:action==='accept'?quote!.quote_revision:null,terms_revision:action==='accept'?quote!.terms_revision:null};
    lockSwitch(true);setPending(command);void perform(command);
  }
  if(error==='denied'||(read.isError&&message(read.error)==='denied')) return <State kind="error" title={t.title} body={t.denied}/>;
  if(read.isPending&&!pending) return <State kind="loading" title={t.title} body={t.loading}/>;
  if(read.isError&&!pending) return <State kind="error" title={t.title} body={message(read.error)==='denied'?t.denied:t.unavailable}><Button onClick={()=>void read.refetch()}>{t.refresh}</Button></State>;
  return <>
    {read.isError&&<State kind="error" title={t.title} body={t.unavailable}/>}
    {error&&<State kind="error" title={t.title} body={t[error as 'denied'|'stale'|'unavailable'|'error']}/>}
    {pending&&<State title={t.reference} body={t.pending}><p><bdi>{pending.operation_id}</bdi></p><p><ButtonLink href={`/${locale}/inbox`} variant="outline">{t.support}</ButtonLink></p><Button disabled={busy} onClick={()=>void perform(pending,true)}>{busy?t.sending:t.retry}</Button></State>}
    {record?<Card><p role="status">{record.state==='accepted'?t.accepted:t.requested}</p><h2>{t.areas}</h2><p>{record.areas.map(area=>t[area]).join(' · ')}</p><h2>{t.currentCondition}</h2><p dir="auto">{record.condition}</p><h2>{t.currentLimits}</h2><p dir="auto">{record.preservation_limits}</p></Card>:<State title={t.title} body={t.empty}/>}
    {record?.state!=='accepted'&&<Card><h2>{t.draft}</h2><form onSubmit={event=>{event.preventDefault();submit('request');}}>
      <Checkbox label={t.case} checked={caseArea} onCheckedChange={setCase} disabled={locked}/>
      <Checkbox label={t.bracelet} checked={bracelet} onCheckedChange={setBracelet} disabled={locked}/>
      <Textarea label={t.condition} value={condition} onValueChange={setCondition} disabled={locked} required/>
      <Textarea label={t.limits} value={limits} onValueChange={setLimits} disabled={locked} required/>
      <Checkbox label={t.permission} checked={permission} onCheckedChange={setPermission} disabled={locked}/>
      <Checkbox label={t.water} checked={water} onCheckedChange={setWater} disabled={locked}/>
      <Checkbox label={t.movement} checked={movement} onCheckedChange={setMovement} disabled={locked}/>
      <Button type="submit" disabled={locked||!permission||!water||!movement||(!caseArea&&!bracelet)||!condition.trim()||!limits.trim()||condition.length>2000||limits.length>2000}>{t.submit}</Button>
    </form></Card>}
    {quote?<Card><h2>{t.quote}</h2><h3>{t.areas}</h3><p>{quote.areas.map(area=>t[area]).join(' · ')}</p>
      <h3>{t.process}</h3><p dir="auto">{quote.process}</p><h3>{t.limitations}</h3><p dir="auto">{quote.limitations}</p>
      <h3>{t.currentCondition}</h3><p dir="auto">{quote.condition}</p><h3>{t.currentLimits}</h3><p dir="auto">{quote.preservation_limits}</p>
      <h3>{t.lead}</h3><p dir="auto">{quote.lead_time}</p><h3>{t.terms}</h3><p dir="auto">{quote.terms}</p>
      <p>{t.amount}: <bdi>{formatAmount(dollars(quote.total_minor),locale,'USD','—')}</bdi></p>
      <p>{t.fee}: <bdi>{formatAmount(dollars(quote.business_fee_minor),locale,'USD','—')}</bdi></p>
      {record?.state!=='accepted'&&<><p>{t.review}</p><p><ButtonLink href={`/${locale}/inbox`} variant="outline">{t.support}</ButtonLink></p><Checkbox label={t.acceptedTerms} checked={terms===quoteKey} onCheckedChange={checked=>setTerms(checked?quoteKey:'')} disabled={locked}/>
      <Button disabled={locked||terms!==quoteKey||!record||quote.request_revision!==record.revision||error==='stale'} onClick={()=>submit('accept')}>{t.accept}</Button></>}
    </Card>:record?.state!=='accepted'&&<State title={t.quote} body={t.absent}/>}
    <Button disabled={busy||Boolean(pending)} onClick={()=>{setResult(null);setTerms('');setError('');void read.refetch();}}>{t.refresh}</Button>
  </>;
}
