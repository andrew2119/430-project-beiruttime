'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AnimatedList, BidiReference, Button, ButtonLink, Card, Input, Textarea } from '@beirut-time/ui';
import { ClipboardCheck, History, ShoppingBag } from 'lucide-react';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { CardHead, LoadingRows, Notice, SectionState } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest, signInHref, useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { buyNowApi } from './api';
import { copy, errorText, uuid, requireAcknowledgedOperation } from './copy';
import type {AllocationOperation} from '@contracts/contracts-orders/allocation';
import HoldControl from './hold-control';
import {formatQuotedMoney} from './money';

export default function OrderDetail({id}:{id:string}) {
  const locale=useLocale(), t=copy(locale), session=useSession();
  const boundary=useQuery({queryKey:['l08-orders',session?.access_fingerprint??'restore'],queryFn:({signal})=>buyNowApi.orders(signal),retry:false});
  if(!session) {
    const outage=boundary.error instanceof ApiError&&boundary.error.status>=500;
    return <PageLayout className="checkout-page"><PageHeader title={t.title} count={t.intro}/><Card>{boundary.isPending?<LoadingRows label={t.loading}/>:<SectionState title={outage?t.unavailable:t.signIn} body={outage?undefined:t.signInBody} kind={outage?'error':'locked'}>{outage?<Button chonk size="sm" onClick={()=>void boundary.refetch()}>{t.reload}</Button>:<ButtonLink href={signInHref('/checkout/'+id,locale)}>{t.signIn}</ButtonLink>}</SectionState>}</Card></PageLayout>;
  }
  return <Detail key={session.access_fingerprint} id={id} fingerprint={session.access_fingerprint}/>;
}

function Detail({id,fingerprint}:{id:string;fingerprint:string}) {
  const locale=useLocale(), t=copy(locale), session=useSession();
  const[organization]=useState(()=>typeof window==='undefined'?null:new URLSearchParams(window.location.search).get('organization_id'));
  const detail=useQuery({queryKey:['l08-order',fingerprint,id,organization],queryFn:({signal})=>buyNowApi.order(id,signal,organization),enabled:uuid.test(id),retry:false});
  const[intakeError,setIntakeError]=useState<unknown>(null), [saved,setSaved]=useState(false), [busy,setBusy]=useState(false), [uncertain,setUncertain]=useState(false);
  const[receiptId,setReceiptId]=useState<string|null>(null);
  const op=useRef<{body:string;key:string}|null>(null), alive=useRef(true);
  useEffect(()=>{alive.current=true;const revoke=()=>{alive.current=false;};window.addEventListener('bt:access-change',revoke);return()=>{alive.current=false;window.removeEventListener('bt:access-change',revoke);};},[]);
  useEffect(()=>{const retain=(event:MouseEvent)=>{if((busy||uncertain)&&event.target instanceof Element&&event.target.closest('a.locale-control')){event.preventDefault();event.stopPropagation();}};document.addEventListener('click',retain,true);return()=>document.removeEventListener('click',retain,true);},[busy,uncertain]);
  const record=detail.data?.order, principal=session?.principal;
  const canIntake=record?.organization_id
    ?principal?.organization_grants?.some(g=>g.organization_id===record.organization_id&&g.permissions.includes('orders.intake'))
    :principal?.permissions.includes('orders.intake');
  const canManage=record?.organization_id
    ?principal?.organization_grants?.some(g=>g.organization_id===record.organization_id&&g.permissions.includes('orders.manage'))
    :principal?.permissions.includes('orders.manage');

  async function intake(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(!record||!alive.current)return;
    const form=event.currentTarget;
    setBusy(true);setIntakeError(null);setSaved(false);
    try {
      if(!op.current) {
        const values=new FormData(form), occurred=new Date(String(values.get('occurred'))+'Z');
        if(Number.isNaN(occurred.getTime()))throw new ApiError(422,'invalid','');
        op.current={key:crypto.randomUUID(),body:JSON.stringify({
          expected_revision:record.revision,actual_watch:values.get('actual_watch'),
          accessories:String(values.get('accessories')??'').split('\n').map(s=>s.trim()).filter(Boolean),
          condition:values.get('condition'),location:values.get('location'),reason:values.get('reason'),occurred_at:occurred.toISOString()
        })};
      }
      const selected=record.organization_id?'?organization_id='+encodeURIComponent(record.organization_id):'';
      const value=await authenticatedRequest<AllocationOperation>(`/api/web/v1/orders/v1/orders/${encodeURIComponent(id)}/intake${selected}`,{
        method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':op.current.key},body:op.current.body
      });
      requireAcknowledgedOperation(value);
      if(!alive.current)return;
      op.current=null;setUncertain(false);setSaved(true);setReceiptId(value.resource_id??null);void detail.refetch();
    } catch(error) {
      if(!alive.current)return;
      setIntakeError(error);
      const unknown=!(error instanceof ApiError)||error.status>=500;
      setUncertain(unknown);
      if(!unknown)op.current=null;
      if(error instanceof ApiError&&error.code==='stale_revision')void detail.refetch();
    } finally { if(alive.current)setBusy(false); }
  }

  return <PageLayout className="checkout-page">
    <PageHeader title={t.history} count={<BidiReference>{id}</BidiReference>} tag={<span className="hx-tag">{t.eyebrow}</span>} lead={<ButtonLink size="sm" variant="ghost" href={`/${locale}/checkout`}>{t.yourOrders}</ButtonLink>}/>
    {!uuid.test(id)&&<p role="alert">{t.invalid}</p>}
    {detail.isPending&&uuid.test(id)&&<Card><LoadingRows label={t.loading}/></Card>}
    {detail.error&&<Card><SectionState title={errorText(detail.error,t)} kind="error"><Button chonk size="sm" onClick={()=>void detail.refetch()}>{t.reload}</Button></SectionState></Card>}
    {record&&<div className="checkout-grid">
      <Card className="checkout-result"><CardHead title={t[record.state]} icon={ShoppingBag}/>{record.is_demo&&<p>{t.sample}</p>}
        <dl><dt>{t.watch}</dt><dd><BidiReference>{record.watch_id}</BidiReference></dd>
          <dt>{t.total}</dt><dd><BidiReference>{formatQuotedMoney(record.total_minor,record.currency,locale)}</BidiReference></dd>
          <dt>{t.deadline}</dt><dd><time dateTime={record.deadline}>{new Date(record.deadline).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time></dd>
          <dt>{t.revision}</dt><dd>{record.revision.toLocaleString(locale)}</dd>
        </dl><Notice>{t.paymentNotice}</Notice>
      </Card>
      <Card><CardHead title={t.history} icon={History}/><AnimatedList className="checkout-history" items={detail.data?.history??[]} getKey={entry=>`${entry.action}-${entry.revision}-${entry.occurred_at}`}>{entry=><div className="checkout-history-row">
        <strong>{entry.action==='reserve'?t.saved:entry.action==='expiry-fence'?t.expired_fenced:entry.action==='payment-hold'?t.payment_unknown:t.intake}</strong>
        <time dateTime={entry.occurred_at}>{new Date(entry.occurred_at).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time>
        <span>{t.revision} {entry.revision.toLocaleString(locale)}</span>
      </div>}</AnimatedList></Card>
    </div>}
    {record&&canManage&&record.state==='awaiting_payment'&&<HoldControl record={record} onRefresh={()=>void detail.refetch()}/>}
    {record&&canIntake&&<Card><CardHead title={t.intake} icon={ClipboardCheck}/><p className="checkout-note">{t.intakeNote}</p>
      <form className="checkout-form" method="post" autoComplete="off" onSubmit={intake}>
        {(['actual_watch','accessories','condition','location','occurred','reason'] as const).map(field=><label key={field}>
          {t[field==='actual_watch'?'actualWatch':field]}
          {field==='accessories'||field==='condition'
            ?<Textarea name={field} maxLength={field==='condition'?2000:4000} disabled={busy||uncertain}/>
            :<Input name={field} type={field==='occurred'?'datetime-local':'text'} required maxLength={field==='actual_watch'?300:200} disabled={busy||uncertain}/>}
        </label>)}
        <Button chonk size="sm" disabled={busy}>{busy?t.loading:uncertain?t.retry:t.recordIntake}</Button>
        {!!intakeError&&<p role="alert">{errorText(intakeError,t)}</p>}{uncertain&&<p role="status">{t.uncertain}</p>}{saved&&<p role="status">{t.intakeSaved}</p>}{receiptId&&<p>{t.receipt}: <BidiReference>{receiptId}</BidiReference></p>}
      </form>
    </Card>}
    <div className="checkout-actions"><ButtonLink size="sm" variant="outline" href={`/${locale}/checkout`}>{t.yourOrders}</ButtonLink></div>
  </PageLayout>;
}
