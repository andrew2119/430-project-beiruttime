'use client';
import {useEffect,useRef,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {BidiReference,Button,Card,CardHead,Checkbox,LoadingRows,Notice,SectionState,Segmented,StatusBadge} from '@beirut-time/ui';
import {CreditCard} from 'lucide-react';
import {useLocale} from '@/shell/locale-context';
import {authenticatedRequest,useSession} from '@/features/identity/session';
import {ApiError} from '@/lib/api/client';
import {readNonSecretDraft,saveNonSecretDraft} from '@/shell/private-state';
import type {CheckoutContext,PaymentOperation,PaymentRoute} from '@contracts/contracts-orders/payments';
import {formatQuotedMoney} from '@/features/buy-now/money';
import en from './en.json';
import ar from './ar.json';

type Pending={owner:string;path:string;body:string;key:string};
const root='/api/web/v1/orders/v1';
function restore(owner:string,id:string):Pending|null{
  try{const v=JSON.parse(readNonSecretDraft(owner,'payment:'+id)??'null');return v&&v.owner===owner&&typeof v.key==='string'&&typeof v.body==='string'&&typeof v.path==='string'&&v.path.startsWith(root+'/')?v:null;}catch{return null;}
}
function pendingRoute(value:Pending|null):PaymentRoute|null{
  try{const route=JSON.parse(value?.body??'{}').route;return route==='card'||route==='whish'||route==='omt'?route:null;}catch{return null;}
}
function persist(owner:string,id:string,value:Pending|null){
  try{
    if(!value){saveNonSecretDraft(owner,'payment:'+id,'null');return;}
    const body=JSON.parse(value.body);
    // Keep only operation intent/opaque references. Financial bytes are re-read
    // from the immutable owned checkout before an uncertain start is resumed.
    delete body.quote_revision;delete body.total_minor;delete body.currency;
    saveNonSecretDraft(owner,'payment:'+id,JSON.stringify({...value,body:JSON.stringify(body)}));
  }catch{/* Storage must never change an acknowledged outcome. */}
}

export default function CheckoutPayment({orderId,onRefresh}:{orderId:string;onRefresh:()=>void}){
  const session=useSession();
  return session?<Payment key={session.access_fingerprint+orderId} orderId={orderId} owner={session.access_fingerprint} onRefresh={onRefresh}/>:null;
}
function Payment({orderId,owner,onRefresh}:{orderId:string;owner:string;onRefresh:()=>void}){
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const detail=useQuery({queryKey:['l13-checkout',owner,orderId],queryFn:({signal})=>authenticatedRequest<CheckoutContext>(`${root}/orders/${orderId}/checkout`,{signal,accessFingerprint:owner}),retry:false,refetchInterval:10000});
  const[selectedRoute,setRoute]=useState<PaymentRoute|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[acceptedTotal,setAcceptedTotal]=useState(false);
  const[pending,setPending]=useState<Pending|null>(()=>restore(owner,orderId));
  const alive=useRef(true),inflight=useRef(false);
  useEffect(()=>{alive.current=true;const purge=()=>{alive.current=false;persist(owner,orderId,null);};window.addEventListener('bt:access-change',purge);return()=>{alive.current=false;window.removeEventListener('bt:access-change',purge);};},[orderId,owner]);
  async function run(path:string,body:unknown){
    if(inflight.current||!alive.current)return;
    inflight.current=true;setBusy(true);setError(null);
    const op=pending??{owner,path,body:JSON.stringify(body),key:crypto.randomUUID()};
    setPending(op);persist(owner,orderId,op);
    try{
      const wire=JSON.parse(op.body);
      if(op.path.endsWith('/payment-attempts')){
        const retained=detail.data?.quote;
        if(op.path!==`${root}/orders/${orderId}/payment-attempts`||!retained)throw new ApiError(503,'checkout_context_unavailable','');
        Object.assign(wire,{quote_revision:retained.revision,total_minor:retained.payable_minor,currency:retained.currency});
      }else if(op.path===`${root}/orders/${orderId}/payment-method`){
        if(!pendingRoute(op))throw new ApiError(503,'method_context_unavailable','');
      }else if(!detail.data?.attempts.some(attempt=>attempt.order_id===orderId&&op.path===`${root}/payment-attempts/${attempt.id}/simulate`))throw new ApiError(503,'attempt_context_unavailable','');
      const value=await authenticatedRequest<PaymentOperation>(op.path,{method:'POST',accessFingerprint:owner,headers:{'Content-Type':'application/json','Idempotency-Key':op.key},body:JSON.stringify(wire)});
      if(value.status==='denied')throw new ApiError(409,value.code??'denied',value.request_id);
      if(op.path.endsWith('/payment-method')){
        if(value.status!=='succeeded'||value.order?.id!==orderId||value.order.currency!=='USD'||value.order.total_minor!==detail.data?.order.total_minor)throw new ApiError(503,'binding_invalid','');
      }else if(!value.attempt||value.attempt.order_id!==orderId||value.attempt.simulated!==true)throw new ApiError(503,'binding_invalid','');
      if(!alive.current)return;
      setPending(null);persist(owner,orderId,null);void detail.refetch();onRefresh();
    }catch(reason){if(alive.current){setError(reason);if(reason instanceof ApiError&&reason.status<500){setPending(null);persist(owner,orderId,null);void detail.refetch();}}}
    finally{inflight.current=false;if(alive.current)setBusy(false);}
  }
  const data=detail.data,quote=data?.quote,attempt=data?.attempts[0],paid=data?.order.state==='paid_held';
  const isJob=data?.order.order_kind==='service_job'||data?.order.order_kind==='customization_job';
  const route=selectedRoute??pendingRoute(pending)??data?.order.payment_method??'card';
  const needsReview=!!quote&&!quote.reviewed_at;
  const routeDeadline=data?.method_deadlines?.[route]??null;
  const routeOpen=!!data&&!!routeDeadline&&Date.parse(data.server_time)<Date.parse(routeDeadline);
  const date=(value:string)=><time dateTime={value}>{new Date(value).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time>;
  const money=(n:number,currency:'USD'|'LBP')=><BidiReference>{formatQuotedMoney(n,currency,locale)}</BidiReference>;
  return <Card className="checkout-slot"><CardHead title={t.title} icon={CreditCard}/><Notice>{t.intro}</Notice>
    {detail.isPending&&<LoadingRows label={t.loading}/>}
    {detail.error&&<SectionState title={detail.error instanceof ApiError&&detail.error.status===403?t.denied:t.unavailable} kind="error"><Button onClick={()=>void detail.refetch()}>{t.reload}</Button></SectionState>}
    {data&&!quote&&<SectionState title={t.legacy} kind="locked"/>}
    {quote&&<><h3>{t.retained}</h3>{quote.sample&&<Notice>{t.sample}</Notice>}<Notice>{isJob?t.jobFeeTerms:t.feeTerms}</Notice><dl className="payment-fees">{(isJob?['price_minor','payable_minor'] as const:['price_minor','buyer_fee_minor','shipping_minor','tax_minor','payable_minor'] as const).map(field=><div key={field}><dt>{{price_minor:isJob?t.jobAmount:t.price,buyer_fee_minor:t.buyerFee,shipping_minor:t.shipping,tax_minor:t.tax,payable_minor:t.total}[field]}</dt><dd>{money(quote[field],quote.currency)}</dd></div>)}</dl>{isJob&&quote.return_fee_minor!=null&&<p>{t.conditionalReturn}: {money(quote.return_fee_minor,quote.currency)}</p>}<p>{t.quoteRevision}: <BidiReference>{quote.revision}</BidiReference></p></>}
    {data&&!paid&&<><Notice>{t.clockTerms}</Notice>{data.order.notified_at?<p>{t.notifiedAt}: {date(data.order.notified_at)}</p>:<SectionState title={t.notificationPending} kind="locked"/>}{data.order.initiation_extended_until&&<p>{t.extensionUntil}: {date(data.order.initiation_extended_until)}</p>}{data.order.state==='expired_released'&&<Notice>{t.released}</Notice>}{data.order.state==='expired_fenced'&&<Notice>{t.hold}</Notice>}</>}
    {paid?<Notice>{isJob?t.jobHeld:t.paid}</Notice>:data&&quote&&!attempt&&!data.payable?<SectionState title={t.notPayable} kind="locked"/>:null}
    {quote&&data&&!paid&&(!attempt||attempt.state==='declined')&&<>{needsReview&&<Checkbox checked={acceptedTotal} disabled={busy||!!pending} onChange={event=>setAcceptedTotal(event.target.checked)}>{t.acceptQuote}</Checkbox>}<Segmented aria-label={t.method} value={route} onChange={v=>{if(busy||pending)return;setRoute(v as PaymentRoute);if(data.order.notified_at)void run(`${root}/orders/${orderId}/payment-method`,{expected_revision:data.order.revision,route:v});}} options={(['card','whish','omt'] as const).map(value=>({value,label:t[value]}))}/>{routeDeadline&&<p>{t.routeDeadline}: {date(routeDeadline)}</p>}<Button disabled={busy||!!pending||!data.payable||!routeOpen||(needsReview&&!acceptedTotal)} onClick={()=>void run(`${root}/orders/${orderId}/payment-attempts`,{expected_revision:data.order.revision,route,quote_revision:quote.revision,total_minor:quote.payable_minor,currency:quote.currency})}>{busy?t.loading:attempt?t.newAttempt:t.start}</Button></>}
    {attempt&&<><StatusBadge hue={attempt.state==='confirmed'?'green':attempt.state==='declined'?'pink':'orange'}>{t[attempt.state]}</StatusBadge><p>{t.reference}: <BidiReference>{attempt.reference}</BidiReference></p>{!paid&&attempt.state==='pending'&&<div className="checkout-actions">{(['confirmed','declined','pending'] as const).map(outcome=><Button key={outcome} variant={outcome==='confirmed'?'default':'outline'} disabled={busy||!!pending} onClick={()=>void run(`${root}/payment-attempts/${attempt.id}/simulate`,{outcome})}>{outcome==='confirmed'?t.pay:outcome==='declined'?t.decline:t.leavePending}</Button>)}</div>}</>}
    {pending&&<><p role="status">{t.uncertain}</p><Button disabled={busy} onClick={()=>void run(pending.path,{})}>{busy?t.loading:t.retry}</Button></>}
    {!!error&&<p role="alert">{error instanceof ApiError&&error.status<500?t.denied:t.unavailable}{error instanceof ApiError&&error.requestId&&<> {t.support}: <BidiReference>{error.requestId}</BidiReference></>}</p>}
  </Card>;
}
