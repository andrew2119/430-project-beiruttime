'use client';
import { normalizeDigits } from '@beirut-time/i18n';
import { useRef, useState, type FormEvent } from 'react';
import { Button, ButtonLink, Card, Checkbox, Input, Segmented, Select, State, Skeleton, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import type { ReductionCommand, ReductionResult } from '@contracts/contracts-service/reduction/v1';
import { recordRead, send, validReference, measurement } from './api';
import { copy } from './copy';
import './styles.css';

function SupportLink() {
  const locale=useLocale();
  return <ButtonLink href={`/${locale}/inbox`} variant="outline">{copy[locale].support}</ButtonLink>;
}

export default function ReductionView() {
  const locale=useLocale(),t=copy[locale],session=useSession(),state=useSessionState();
  return <PageFrame><PageHeader title={t.title} lead={t.measurement}/><PageBody>
    {session?<PrivateView key={session.access_fingerprint} access={session.access_fingerprint}/>:<State kind={state==='restoring'?'loading':'error'} title={state==='restoring'?t.loading:t.unavailable} body={t.signIn}/>}
  </PageBody></PageFrame>;
}
function PrivateView({access}:{access:string}) {
  const locale=useLocale(),t=copy[locale];
  const [record,setRecord]=useState(''),[organization,setOrganization]=useState(''),[binding,setBinding]=useState<{record:string;organization:string}|null>(null);
  const [locked,setLocked]=useState(false);
  return <div className="reduction-stack"><Card><form onSubmit={event=>{event.preventDefault();if(!locked&&validReference(record)&&validReference(organization))setBinding({record,organization});}}>
    <Input label={t.record} value={record} onValueChange={setRecord} required/>
    <Input label={t.organization} value={organization} onValueChange={setOrganization} required/>
    <Button type="submit" disabled={locked||!validReference(record)||!validReference(organization)}>{t.open}</Button>
  </form></Card>{binding&&<RecordForm key={`${binding.record}:${binding.organization}`} binding={binding} access={access} onPending={setLocked}/>}</div>;
}
export function RecordForm({binding,access,onPending}:{binding:{record:string;organization:string};access:string;onPending:(value:boolean)=>void}) {
  const locale=useLocale(),t=copy[locale];
  const query=usePageRead(recordRead(binding.record,binding.organization,access));
  const [target,setTarget]=useState(''),[unit,setUnit]=useState<'cm'|'mm'>('cm'),[source,setSource]=useState(''),[method,setMethod]=useState('');
  const [choice,setChoice]=useState(''),[recipient,setRecipient]=useState(''),[removed,setRemoved]=useState<string[]>([]),[returned,setReturned]=useState<string[]>([]),[exception,setException]=useState('');
  const [strap,setStrap]=useState(''),[fit,setFit]=useState(false),[result,setResult]=useState<ReductionResult|null>(null),[status,setStatus]=useState<'idle'|'pending'|'denied'|'stale'|'unavailable'|'invalid'>('idle');
  const pending=useRef<ReductionCommand|null>(null),busy=useRef(false);
  const [operationReference,setOperationReference]=useState<string|null>(null);
  const answer=query.data,context=answer?.context,saved=result??answer?.record;
  const messages={placeholder:t.choice,filter:t.choice,emptyTitle:t.empty,emptyBody:t.emptyBody,close:locale==='ar'?'إغلاق':'Close',loading:t.loading,errorTitle:t.unavailable,errorBody:t.unavailableBody,retry:t.refresh};
  const uncertain=operationReference!==null;
  async function submit(event?:FormEvent) {
    event?.preventDefault();if(busy.current||!context)return;
    if(!pending.current) {
      const actual=!!saved;
      if(!actual&&(!measurement(normalizeDigits(target),unit)||!source.trim()||!method.trim()||!choice||!recipient)){setStatus('invalid');return;}
      pending.current={schema_version:'reduction.command.v1',operation_id:crypto.randomUUID(),subject_id:context.subject_id,watch_id:context.watch_id,organization_id:context.organization_id,source_revision:context.source_revision,quote_id:context.quote_id,quote_revision:context.quote_revision,policy_revision:context.policy_revision,
        expected_revision:saved?.revision??0,kind:actual?'record':'request',choice_id:saved?.choice_id??choice,target:saved?.target??{value:normalizeDigits(target),unit,source,method},recipient_id:saved?.recipient_id??recipient,
        removed_link_ids:actual?removed:[],returned_link_ids:actual?returned:[],exception_id:actual&&exception?exception:null,fit_confirmed:actual&&fit,actual_strap_id:actual&&strap?strap:null};
    }
    setOperationReference(pending.current.operation_id);onPending(true);busy.current=true;setStatus('pending');
    try {const next=await send(binding.record,access,pending.current);setResult(next);pending.current=null;setOperationReference(null);onPending(false);setStatus('idle');}
    catch(error){if(error instanceof ApiError&&[401,403,409,422].includes(error.status)){pending.current=null;setOperationReference(null);onPending(false);setStatus(error.status===409?'stale':error.status===422?'invalid':'denied');}else setStatus('pending');}
    finally{busy.current=false;}
  }
  if(query.isPending)return <div role="status" aria-label={t.loading}><Skeleton size="card"/></div>;
  if(status==='denied')return <State kind="error" title={t.denied} body={t.deniedBody}><Button onClick={()=>{setStatus('idle');setResult(null);void query.refetch();}}>{t.refresh}</Button><SupportLink/></State>;
  if(query.error||!context) {
    const denied=query.error instanceof ApiError&&[401,403].includes(query.error.status);
    return <State kind="error" title={denied?t.denied:t.unavailable} body={denied?t.deniedBody:t.unavailableBody}><Button onClick={()=>void query.refetch()}>{t.refresh}</Button><SupportLink/></State>;
  }
  const disabled=uncertain||status==='stale';
  const isWork=!!saved&&context.permission==='assigned_work';
  function toggle(values:string[],value:string,on:boolean) {return on?[...values.filter(item=>item!==value),value]:values.filter(item=>item!==value);}
  return <Card><div className="reduction-stack" data-page-answer>
    {saved?<State title={t[saved.state]} body={saved.state==='unresolved'?t.unresolvedBody:t.recordedBody}/>:<State title={t.empty} body={t.emptyBody}/>}
    {saved&&<><p>{formatNumber(Number(saved.target.value),locale)} {t[saved.target.unit]} · {saved.target.source} · {saved.target.method}</p><p>{t.recipient}: <bdi>{saved.recipient_id}</bdi></p><p>{t.counts}: {formatNumber(saved.removed_count,locale)} / {formatNumber(saved.returned_count,locale)}</p></>}
    {status!=='idle'&&<State kind={status==='pending'?'loading':'error'} title={status==='invalid'?t.invalid:t[status]} body={status==='invalid'?t.invalid:status==='pending'?t.pendingBody:status==='stale'?t.staleBody:t.unavailableBody}/>}
    {operationReference&&<p>{t.reference}: <bdi>{operationReference}</bdi></p>}
    <form className="reduction-stack" onSubmit={event=>void submit(event)}>
      {!saved&&context.permission==='buyer_request'&&<>
        <Select label={t.choice} options={context.choices.filter(item=>item.compatible).map(item=>({value:item.id,label:`${t[item.kind]} · ${item.id}`}))} value={choice} onValueChange={setChoice} messages={messages} disabled={disabled}/>
        <Input label={t.target} value={target} onValueChange={setTarget} inputMode="decimal" disabled={disabled} required/>
        <Segmented label={t.unit} value={unit} onValueChange={value=>setUnit(value as 'cm'|'mm')} options={[{value:'cm',label:t.cm},{value:'mm',label:t.mm}]} disabled={disabled} locale={locale}/>
        <Input label={t.source} value={source} onValueChange={setSource} disabled={disabled} required/>
        <Input label={t.method} value={method} onValueChange={setMethod} disabled={disabled} required/>
        <Select label={t.recipient} value={recipient} onValueChange={setRecipient} options={context.authorized_recipient_ids.map(id=>({value:id,label:id}))} messages={messages} disabled={disabled}/>
      </>}
      {isWork&&<><fieldset disabled={disabled}><legend>{t.removed}</legend>{context.removable_link_ids.map(id=><Checkbox key={id} label={id} checked={removed.includes(id)} onCheckedChange={on=>{setRemoved(toggle(removed,id,on));if(!on)setReturned(returned.filter(value=>value!==id));}}/>)}</fieldset>
        <fieldset disabled={disabled}><legend>{t.returned}</legend>{removed.map(id=><Checkbox key={id} label={id} checked={returned.includes(id)} onCheckedChange={on=>setReturned(toggle(returned,id,on))}/>)}</fieldset>
        <Select label={t.exception} value={exception} onValueChange={setException} options={[{value:'',label:t.none},...context.accepted_exceptions.map(item=>({value:item.id,label:`${t[item.basis]} · ${item.id}`}))]} messages={messages} disabled={disabled}/>
        {context.choices.find(item=>item.id===saved?.choice_id)?.kind==='strap_change'&&<Select label={t.strap} value={strap} onValueChange={setStrap} options={(context.accepted_straps??[]).filter(item=>item.compatible&&item.choice_id===saved?.choice_id&&item.source_revision===context.source_revision&&item.quote_revision===context.quote_revision&&item.policy_revision===context.policy_revision).map(item=>({value:item.id,label:item.id}))} messages={messages} disabled={disabled}/>}
        <Checkbox label={t.fit} checked={fit} onCheckedChange={setFit} disabled={disabled}/>
      </>}
      {(!saved&&context.permission==='buyer_request'||isWork)&&<Button type="submit" disabled={disabled}>{saved?t.save:t.submit}</Button>}
    </form>
    {uncertain&&<Button onClick={()=>void submit()}>{t.retry}</Button>}
    <Button onClick={()=>{if(!uncertain){setResult(null);setStatus('idle');void query.refetch();}}} disabled={uncertain}>{t.refresh}</Button><SupportLink/>
  </div></Card>;
}
