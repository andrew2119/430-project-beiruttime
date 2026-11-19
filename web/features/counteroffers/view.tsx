'use client';
import { useLayoutEffect, useRef, useState } from 'react';
import { Button, Card, Checkbox, Input, State, formatAmount } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { usePageRead } from '@/lib/page-speed/read';
import type { PageRead } from '@/lib/page-speed/definition';
import type { Command, Counter, Economics, Operation } from '@contracts/contracts-pricing/counteroffers';
import { useLocale } from '@/shell/locale-context';
import { commandFor, operationMatches, currentCounter, dollars, permissionDenied, termsMatch, type BoundTerms } from './model';
import { copy } from './copy';

type Props = {
  terms?:BoundTerms;
  scope:string; subjectId:string; watchId:string; actor:string; sourceRevision:number; authorityRevision:number; read:PageRead<Counter|null>|null;
  send:(command:Command)=>Promise<Operation>;
  lookup:(command:Command)=>Promise<Operation>;
  quote:(price:number,counter:Counter)=>Promise<Economics>;
};
/** Scope includes current identity and access revision, never the locale. */
export default function CounterofferView(props:Props) {
  return <CounterofferForm terms={props.terms} key={JSON.stringify([props.scope,props.subjectId,props.watchId,props.actor])} subjectId={props.subjectId} watchId={props.watchId} scope={props.scope} actor={props.actor} sourceRevision={props.sourceRevision}
    authorityRevision={props.authorityRevision} read={props.read} send={props.send} lookup={props.lookup} quote={props.quote}/>;
}
function CounterofferForm({terms,subjectId,watchId,actor,read,send,lookup,quote,sourceRevision,authorityRevision}:Props) {
  const locale=useLocale(),t=copy[locale==='ar'?'ar':'en'];
  const current=usePageRead(read);
  const [accessDenied,setAccessDenied]=useState(false);
  const [returned,setReturned]=useState<Counter|null>(null);
  const denied=accessDenied||permissionDenied(current.error);
  const counter=currentCounter(current.data,returned,denied,subjectId,watchId);
  const [amount,setAmount]=useState(''),[review,setReview]=useState<number|null>(null);
  const [preview,setPreview]=useState<{economics:Economics;revision:number;source:number;authority:number}|null>(null);
  const [operation,setOperation]=useState<Command|null>(null),[result,setResult]=useState<Operation|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(false);
  const flight=useRef(false),alive=useRef(true),revoked=useRef(false);
  // Each completion checks the mounted scope before retaining private data.
  const binding=useRef(read);
  useLayoutEffect(()=>{binding.current=read;},[read]);
  useLayoutEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  function clearPrivate() {
    revoked.current=true;setAccessDenied(true);setAmount('');setReview(null);setPreview(null);
    setOperation(null);setResult(null);setReturned(null);setError(false);
  }
  useLayoutEffect(()=>{
    if(permissionDenied(current.error)) {
      revoked.current=true;
      queueMicrotask(()=>{if(alive.current)clearPrivate();});
    }
  },[current.error]);
  function receive(answer:Operation, command:Command) {
    if(revoked.current||!operationMatches(answer,command))return;
    if(answer.state==='denied' && answer.code==='denied'){clearPrivate();return;}
    setResult(answer);
    if(answer.current){setReturned(answer.current);setReview(null);setPreview(null);}
  }
  function failed(cause:unknown) {if(permissionDenied(cause))clearPrivate();else setError(true);}
  const unresolved=!!operation&&(!result||result.state==='pending'||result.state==='unavailable');
  const validPreview=preview?.revision===counter?.revision&&preview?.source===sourceRevision&&preview?.authority===authorityRevision?preview.economics:null;
  async function act(kind:Command['kind']) {
    if (!counter||denied||flight.current||unresolved||(kind==='accept'&&!termsMatch(terms,counter.economics))) return;
    const command=commandFor(counter,actor,kind,kind==='propose'?validPreview??counter.economics:counter.economics,
      review===counter.revision,crypto.randomUUID(),sourceRevision,authorityRevision);
    setOperation(command);setResult(null);setBusy(true);flight.current=true;setError(false);
    const expected=read;
    try {const answer=await send(command);if(binding.current===expected&&alive.current&&answer.operation_id===command.operation_id)receive(answer,command);}
    catch (cause) {if(binding.current===expected&&alive.current)failed(cause);}
    finally {flight.current=false;setBusy(false);}
  }
  async function recover(replay=false) {
    if(!operation||flight.current)return;
    flight.current=true;setBusy(true);const expected=read;
    try {const answer=await (replay?send(operation):lookup(operation));if(binding.current===expected&&alive.current&&answer.operation_id===operation.operation_id){receive(answer,operation);setError(false);}}
    catch (cause) {if(binding.current===expected&&alive.current)failed(cause);}
    finally {flight.current=false;setBusy(false);}
  }
  const economics=actor===counter?.seller_id?validPreview??counter.economics:counter?.economics;
  const money=(minor:number)=>formatAmount(`${Math.floor(minor/100)}.${String(minor%100).padStart(2,'0')}`,locale,'USD','—');
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    {denied&&<State kind="error" title={t.title} body={t.denied}/>}
    {!denied&&read&&current.isPending&&<State kind="loading" title={t.title} body={t.loading}/>}
    {(!denied&&(current.isError||!read))&&<State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>void current.refetch()}>{t.refresh}</Button></State>}
    {!denied&&current.isSuccess&&!counter&&<State title={t.title} body={t.empty}/>}
    {counter&&economics&&<Card><p className="bt-text">{counter.state==='sent'?t.sent:t.closed}</p>
      <dl><dt>{t.price}</dt><dd>{money(economics.price_minor)}</dd><dt>{t.fee}</dt><dd>{money(economics.buyer_fee_minor)}</dd>
        <dt>{t.commission}</dt><dd>{money(economics.seller_commission_minor)}</dd><dt>{t.total}</dt><dd>{money(economics.total_minor)}</dd>
        <dt>{t.terms}</dt><dd>{economics.terms_revision}</dd><dt>{t.expires}</dt><dd><bdi>{counter.expires_at}</bdi></dd></dl>
      <p className="bt-text">{t.retained}</p>
      {actor===counter.seller_id&&<>
        <Input id="counter-price" label={t.amount} inputMode="decimal" value={amount} disabled={busy||unresolved} onValueChange={value=>{if(value.length>14)return;setAmount(value);setPreview(null);setReview(null);}}/>
        {amount&&dollars(amount)===null&&<p role="alert">{t.invalid}</p>}
        <Button disabled={busy||unresolved||dollars(amount)===null} onClick={async()=>{
          if(flight.current)return;flight.current=true;setBusy(true);const expected=read;
          try{const next=await quote(dollars(amount)!,counter);if(binding.current===expected&&alive.current&&!revoked.current){setPreview({economics:next,revision:counter.revision,source:sourceRevision,authority:authorityRevision});setReview(null);}}
          catch(cause){if(binding.current===expected&&alive.current)failed(cause);}finally{flight.current=false;setBusy(false);}
        }}>{t.quote}</Button></>}
      {termsMatch(terms,economics)&&terms&&<section aria-label={t.terms}>
        <p>{terms[locale==='ar'?'ar':'en'].terms}</p>
        <p>{terms[locale==='ar'?'ar':'en'].returns}</p>
        <p>{terms[locale==='ar'?'ar':'en'].assurance}</p>
        <a href={terms.support_href}>{t.support}</a>
      </section>}
      {!termsMatch(terms,economics)&&<p role="status">{t.termsUnavailable}</p>}
      <Checkbox label={t.review} checked={review===counter.revision} disabled={busy||unresolved||counter.state!=='sent'||!termsMatch(terms,economics)} onCheckedChange={checked=>setReview(checked?counter.revision:null)}/>
      {(actor===counter.seller_id||actor===counter.buyer_id)&&<Button disabled={busy||unresolved||counter.state!=='sent'||!termsMatch(terms,economics)||review!==counter.revision||(actor===counter.seller_id&&!validPreview)} onClick={()=>void act(actor===counter.seller_id?'propose':'accept')}>{actor===counter.seller_id?t.propose:t.accept}</Button>}
      {actor===counter.buyer_id&&<Button disabled={busy||unresolved||counter.state!=='sent'} onClick={()=>void act('reject')}>{t.reject}</Button>}
    </Card>}
    {!denied&&operation&&<p>{t.reference}: <bdi>{operation.operation_id}</bdi></p>}
    {!denied&&unresolved&&<State kind="loading" title={t.title} body={t.pending}><Button disabled={busy} onClick={()=>void recover()}>{t.retry}</Button><Button disabled={busy} onClick={()=>void recover(true)}>{t.replay}</Button></State>}
    {!denied&&result&&result.state==='denied'&&<State kind="error" title={t.title} body={result.code==='stale_revision'||result.code==='review_current_fees'?t.stale:t.denied}><Button onClick={()=>void current.refetch()}>{t.refresh}</Button></State>}
    {!denied&&result?.state==='succeeded'&&<State title={t.title} body={result.code==='closed'||result.current?.state==='closed'?t.closed:t.done}><Button onClick={()=>void current.refetch()}>{t.refresh}</Button></State>}
    {!denied&&error&&<State kind="error" title={t.title} body={t.unavailable}/>}
  </PageBody></PageFrame>;
}
