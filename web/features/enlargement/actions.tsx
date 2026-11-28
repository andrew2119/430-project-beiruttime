'use client';
import { useRef, useState } from 'react';
import { Button, Checkbox, Input, Select, State, formatAmount } from '@beirut-time/ui/foundation';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { type RecordView } from './api';
import en from './en.json';
import ar from './ar.json';

export type ActionDraft = {values:Record<string,string>;completed:string[];checked:boolean;acknowledgedQuote?:string};
export const emptyActionDraft = ():ActionDraft => ({values:{partStatus:'available',choice:'links'},completed:[],checked:false});
export function Actions({record,submitAction,draft,onDraftChange}:{record:RecordView;submitAction:(body:object)=>Promise<void>;draft:ActionDraft;onDraftChange:(draft:ActionDraft)=>void}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const {values,completed,checked}=draft;
  const setValues=(update:(previous:Record<string,string>)=>Record<string,string>)=>onDraftChange({...draft,values:update(values)});
  const setCompleted=(update:(previous:string[])=>string[])=>onDraftChange({...draft,completed:update(completed)});
  const quoteSnapshot=JSON.stringify([record.request_id,record.watch_id,record.organization_id,
    record.source_revision,record.assessment,record.quote_lines,record.quote_terms]);
  const acknowledged=checked && draft.acknowledgedQuote===quoteSnapshot;
  const setChecked=(checked:boolean)=>onDraftChange({...draft,checked,acknowledgedQuote:quoteSnapshot});
  const [busy,setBusy]=useState(false),[error,setError]=useState('');

  const [uncertain,setUncertain]=useState(false);
  const inFlight=useRef(false);
  const allowed=record.allowed_operations??[];
  const kind=allowed.find(value=>['assess','accept','work','fit'].includes(value));
  if (!kind) return null;
  const fields=kind==='assess'?['partId','partRevision','quantity','quoteId','quoteRevision','termsRevision','expires','minor','assessedTarget','limitations']:kind==='work'?['performed']:kind==='fit'?['fit','tests','returned']:[];
  async function send() {
    if (inFlight.current || kind==='accept' && (!acknowledged||!record.quote_lines?.length||!record.quote_terms?.en||!record.quote_terms?.ar)) return;
    inFlight.current=true;
    setBusy(true);setError('');
    try {
      const payload=kind==='assess'?{parts:[{id:values.partId,revision:Number(values.partRevision),quantity:Number(values.quantity),kind:values.choice,status:values.partStatus}],target:values.assessedTarget,limitations:values.limitations,quote_id:values.quoteId,quote_revision:Number(values.quoteRevision),terms_revision:Number(values.termsRevision),expires_at:values.expires,total_minor:dollars(values.minor)}:
          kind==='accept'?{quote_id:record.assessment?.quote_id,quote_revision:record.assessment?.quote_revision,terms_revision:record.assessment?.terms_revision,accepted_line_ids:record.quote_lines?.map(line=>line.id)}:
          kind==='work'?{performed:values.performed,part_ids:record.assessment?.parts.map(part=>part.id),completed_line_ids:completed}:
          {fit:values.fit,tests:values.tests,returned_parts:values.returned,passed:checked,work_revision:record.revision};
        const body={schema_version:'enlargement.v1',operation_id:crypto.randomUUID(),request_id:record.request_id,watch_id:record.watch_id,organization_id:record.organization_id,source_revision:record.source_revision,expected_revision:record.revision,kind,payload};
        setUncertain(true);
        await submitAction(body);
        setUncertain(false);
    } catch(failure) {if(failure instanceof ApiError && [400,403,409,422].includes(failure.status)){setUncertain(false);}
      setError(failure instanceof ApiError && failure.status===403?t.denied:failure instanceof ApiError && failure.status===409?t.stale:failure instanceof ApiError && failure.status===422?t.invalid:failure instanceof Error && failure.message==='invalid_amount'?t.invalid:t.actionPending);}
    finally {inFlight.current=false;setBusy(false);}
  }
  const title=kind==='assess'?t.assess:kind==='accept'?t.confirm:kind==='work'?t.work:t.fitAction;
  return <form onSubmit={event=>{event.preventDefault();void send();}}><h3>{title}</h3>
    {fields.map(name=><Input key={name} required disabled={busy||uncertain} label={String(t[name as keyof typeof t])} value={values[name]??''} onValueChange={value=>setValues(previous=>({...previous,[name]:value}))}/>)}
    {kind==='assess' && <><Select label={t.choice} value={values.choice} messages={t.select} disabled={busy||uncertain} options={(['links','strap','clasp'] as const).map(value=>({value,label:t[value]}))} onValueChange={choice=>setValues(previous=>({...previous,choice}))}/><Select label={t.partStatus} value={values.partStatus} messages={t.select} disabled={busy||uncertain} options={(['supplied','ordered','available','unavailable'] as const).map(value=>({value,label:t.statuses[value]}))} onValueChange={partStatus=>setValues(previous=>({...previous,partStatus}))}/></>}
    {kind==='accept' && <>{record.quote_lines?.map(line=><p key={line.id}>{locale==='ar'?line.label_ar:line.label_en} · {formatAmount((line.amount_minor/100).toFixed(2),locale,'USD','—')}</p>)}<p>{record.quote_terms?.[locale]}</p><Checkbox label={t.termsCheck} checked={acknowledged} disabled={busy||uncertain} onCheckedChange={setChecked}/></>}
    {kind==='work' && record.quote_lines?.map(line=><Checkbox key={line.id} label={locale==='ar'?line.label_ar:line.label_en} checked={completed.includes(line.id)} disabled={busy||uncertain} onCheckedChange={yes=>setCompleted(previous=>yes?[...previous,line.id]:previous.filter(id=>id!==line.id))}/>)}
    {kind==='fit' && <Checkbox label={t.pass} checked={checked} disabled={busy||uncertain} onCheckedChange={setChecked}/>}
    <Button type="submit" disabled={busy || kind==='accept' && (!acknowledged||!record.quote_lines?.length||!record.quote_terms?.en||!record.quote_terms?.ar)}>{uncertain?t.retry:t.newAction}</Button>
    {error && <State kind="error" title={title} body={error}/>}
  </form>;
}
function dollars(value:string) {
  if (!/^\d{1,10}(?:\.\d{1,2})?$/.test(value)) throw new Error('invalid_amount');
  const [whole,fraction='']=value.split('.');return Number(whole)*100+Number(fraction.padEnd(2,'0'));
}
