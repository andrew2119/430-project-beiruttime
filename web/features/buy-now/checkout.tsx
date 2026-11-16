'use client';
import {useEffect,useRef,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {AnimatedList,BidiReference,Button,ButtonLink,Card,CardHead,Checkbox,LoadingRows,Notice,SectionState} from '@beirut-time/ui';
import {ShoppingBag} from 'lucide-react';
import {PageHeader,PageLayout} from '@/shell/page-header';
import {useLocale} from '@/shell/locale-context';
import {authenticatedRequest,useSession,signInHref} from '@/features/identity/session';
import {ApiError} from '@/lib/api/client';
import {readNonSecretDraft,saveNonSecretDraft} from '@/shell/private-state';
import type {AllocationOperation,Order} from '@contracts/contracts-orders/allocation';
import type {ExactQuote} from '@contracts/contracts-orders/payments';
import {buyNowApi} from './api';
import {formatQuotedMoney} from './money';
import {connectedCopy} from './connected-copy';
import {readQuoteSelection,rememberQuoteSelection,clearQuoteSelection} from './quote-memory';

type Context={listing:{id:string;revision:number;physical_watch_id:string;is_demo:boolean;facts:{brand:string;model:string;currency:'USD'|'LBP';price_minor:number}};watch:{watch_id:string;listing_id:string;revision:number;status:string;sale_mode:string}};
type Intent={owner:string;listingId:string;watch:string;quote:string;body:{watch_id:string;quote_id:string;expected_revision:number};key:string};
function stored(owner:string):Intent|null{try{const v=JSON.parse(readNonSecretDraft(owner,'checkout-operation')??'null');return v?.owner===owner?v:null;}catch{return null;}}
function persistIntent(owner:string,intent:Intent|null){try{saveNonSecretDraft(owner,'checkout-operation',JSON.stringify(intent));}catch{/* Storage is optional; never change an acknowledgement. */}}
const pricing='/api/web/v1/pricing/v1/quotes';
function post(body:unknown,key:string):RequestInit{return {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)};}

export default function Checkout({listingId='',watchId=''}:{listingId?:string;watchId?:string}){
  const locale=useLocale(),t=connectedCopy[locale],session=useSession();
  const boundary=useQuery({queryKey:['l08-orders',session?.access_fingerprint??'restore'],queryFn:({signal})=>buyNowApi.orders(signal),retry:false});
  const outage=boundary.error instanceof ApiError&&boundary.error.status>=500;
  return <PageLayout className="checkout-page"><PageHeader title={t.title} count={t.intro}/>{!session?<Card>{boundary.isPending?<LoadingRows label={t.loading}/>:<SectionState title={outage?t.unavailable:t.signIn} kind={outage?'error':'locked'}><ButtonLink href={signInHref('/checkout'+(listingId?'?listing_id='+encodeURIComponent(listingId):''),locale)}>{t.signIn}</ButtonLink></SectionState>}</Card>:<Body key={session.access_fingerprint} owner={session.access_fingerprint} listingId={listingId} watchId={watchId}/>}</PageLayout>;
}
function Body({owner,listingId,watchId}:{owner:string;listingId:string;watchId:string}){
  const locale=useLocale(),t=connectedCopy[locale];
  const[initial]=useState(()=>stored(owner));
  const[selection]=useState(()=>readQuoteSelection(owner));
  const[ignoreSelection,setIgnoreSelection]=useState(false);
  const selected=listingId||initial?.listingId||(!watchId?selection?.listingId:undefined);
  const watch=useQuery({queryKey:['l13-checkout-watch',owner,watchId],queryFn:({signal})=>buyNowApi.availability(watchId,signal),enabled:!!watchId&&!selected,retry:false});
  const id=selected||watch.data?.listing_id;
  const context=useQuery({queryKey:['l13-context',owner,id],queryFn:({signal})=>authenticatedRequest<Context>('/api/web/v1/orders/v1/checkout-context?listing_id='+encodeURIComponent(id!),{signal,accessFingerprint:owner}),enabled:!!id,retry:false});
  const orders=useQuery({queryKey:['l08-orders',owner],queryFn:({signal})=>buyNowApi.orders(signal),retry:false});
  const retained=useQuery({queryKey:['l13-selected-quote',owner,selection?.quoteId],queryFn:({signal})=>authenticatedRequest<ExactQuote>(`${pricing}/${selection!.quoteId}`,{signal,accessFingerprint:owner}),enabled:!!context.data&&!context.isFetching&&!!selection&&!ignoreSelection&&selection.listingId===id,retry:false});
  const[createdQuote,setQuote]=useState<ExactQuote|null>(null),[accepted,setAccepted]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[pending,setPending]=useState<Intent|null>(initial),[result,setResult]=useState<Order|null>(null);
  const candidate=createdQuote??(!ignoreSelection&&selection?.listingId===id?retained.data:null);
  const quote=candidate?.currency==='USD'?candidate:null;
  const createKey=useRef(crypto.randomUUID()),reviewKey=useRef(crypto.randomUUID()),alive=useRef(true),inflight=useRef(false);
  useEffect(()=>{alive.current=true;const purge=()=>{alive.current=false;persistIntent(owner,null);clearQuoteSelection(owner);};window.addEventListener('bt:access-change',purge);return()=>{alive.current=false;window.removeEventListener('bt:access-change',purge);};},[owner]);
  async function getQuote(){
    if(!context.data||inflight.current)return;
    inflight.current=true;setBusy(true);setError(null);
    const listing=context.data.listing;
    try{
      const value=await authenticatedRequest<ExactQuote>(pricing,post({subject_id:listing.id,subject_revision:listing.revision,purpose:'purchase',source:'listing',currency:listing.facts.currency,price_minor:listing.facts.price_minor,schedule_id:'usd-v2'},createKey.current));
      if(value.currency!=='USD'||value.subject_id!==listing.id||value.subject_revision!==listing.revision||value.source_verified!==true||!Number.isSafeInteger(value.payable_minor))throw new ApiError(503,'quote_binding_mismatch','');
      if(alive.current){setQuote(value);setAccepted(false);rememberQuoteSelection({owner,listingId:listing.id,quoteId:value.id});}
    }catch(reason){if(alive.current)setError(reason);}finally{inflight.current=false;if(alive.current)setBusy(false);}
  }
  async function reserve(){
    if(inflight.current||!alive.current||(!pending&&(!quote||!context.data||!accepted)))return;
    inflight.current=true;setBusy(true);setError(null);
    try{
      let intent=pending;
      if(!intent){
        const q=quote!,c=context.data!;
        if(!q.reviewed_at)await authenticatedRequest<ExactQuote>(`${pricing}/${q.id}/review`,post({subject_id:q.subject_id,subject_revision:q.subject_revision,purpose:q.purpose,source:q.source,currency:q.currency,price_minor:q.price_minor,schedule_id:q.schedule_id,quote_revision:q.revision,payable_minor:q.payable_minor},reviewKey.current));
        intent={owner,listingId:c.listing.id,watch:c.watch.watch_id,quote:q.id,body:{watch_id:c.watch.watch_id,quote_id:q.id,expected_revision:c.watch.revision},key:crypto.randomUUID()};
        if(!alive.current)return;
        setPending(intent);persistIntent(owner,intent);
      }
      const value=await authenticatedRequest<AllocationOperation>('/api/web/v1/orders/v1/exact-reservations',post(intent.body,intent.key));
      if(value.status==='denied')throw new ApiError(409,value.code??'denied',value.request_id);
      if(value.status!=='succeeded'||!value.order||value.order.watch_id!==intent.watch||value.order.quote_id!==intent.quote)throw new ApiError(503,'allocation_pending','');
      if(!alive.current)return;
      setResult(value.order);setPending(null);persistIntent(owner,null);void orders.refetch();
    }catch(reason){if(alive.current){setError(reason);if(reason instanceof ApiError&&reason.status<500){setPending(null);persistIntent(owner,null);void context.refetch();}}}finally{inflight.current=false;if(alive.current)setBusy(false);}
  }
  const c=context.data,allowed=c?.watch.status==='available'&&c.watch.sale_mode==='fixed';
  const quoteMatches=quote&&c&&quote.subject_id===c.listing.id&&quote.subject_revision===c.listing.revision&&quote.source==='listing'&&quote.source_verified===true&&quote.purpose==='purchase';
  const failure=error??(candidate&&candidate.currency!=='USD'?new ApiError(409,'legacy_currency_reconciliation_required',''):!createdQuote?retained.error:null);
  function resetQuote(){if(busy||pending)return;clearQuoteSelection(owner);setIgnoreSelection(true);setQuote(null);setAccepted(false);setError(null);createKey.current=crypto.randomUUID();reviewKey.current=crypto.randomUUID();}
  return <><div className="checkout-grid"><Card className="checkout-slot"><CardHead title={t.selected} icon={ShoppingBag}/>
    {!id&&!watchId&&<SectionState title={t.empty} icon={ShoppingBag}><ButtonLink href={`/${locale}/watches`}>{t.browse}</ButtonLink></SectionState>}
    {(watch.isFetching||context.isFetching||retained.isFetching)&&<LoadingRows label={t.loading}/>}
    {(watch.error||context.error)&&<SectionState title={(context.error instanceof ApiError&&context.error.status<500)?t.denied:t.unavailable} kind="error"><Button onClick={()=>void (id?context.refetch():watch.refetch())}>{t.reload}</Button></SectionState>}
    {c&&<><h2>{c.listing.facts.brand} {c.listing.facts.model}</h2>{c.listing.is_demo&&<Notice>{t.sample}</Notice>}{!allowed&&!result&&!pending?<SectionState title={t.missing} kind="locked"/>:!quote&&!result&&!pending&&<Button disabled={busy||retained.isFetching} onClick={()=>void getQuote()}>{busy||retained.isFetching?t.loading:t.review}</Button>}</>}
    {quote&&!result&&<><h3>{t.ready}</h3><Notice>{t.fees}</Notice><dl className="payment-fees">{(['price_minor','buyer_fee_minor','shipping_minor','tax_minor','payable_minor'] as const).map((field,i)=><div key={field}><dt>{[t.price,t.fee,t.shipping,t.tax,t.total][i]}</dt><dd><BidiReference>{formatQuotedMoney(quote[field],quote.currency,locale)}</BidiReference></dd></div>)}</dl><Checkbox checked={accepted} onChange={e=>setAccepted(e.target.checked)} disabled={busy||!!pending||!quoteMatches||!allowed}>{t.terms}</Checkbox><Button disabled={busy||!accepted||!!pending||!quoteMatches||!allowed} onClick={()=>void reserve()}>{busy?t.loading:t.accept}</Button><Button variant="outline" disabled={busy||!!pending} onClick={resetQuote}>{t.newQuote}</Button></>}
    {pending&&<><p role="status">{t.pending}</p><Button disabled={busy} onClick={()=>void reserve()}>{busy?t.loading:t.retry}</Button></>}
    {result&&<ButtonLink href={`/${locale}/checkout/${result.id}`}>{t.open}</ButtonLink>}
    {!!failure&&<><p role="alert">{failure instanceof ApiError&&failure.status<500?t.denied:t.unavailable}</p><Button variant="outline" disabled={busy} onClick={()=>{setError(null);void context.refetch();if(selection&&!ignoreSelection)void retained.refetch();}}>{t.reload}</Button></>}
    </Card><Card><CardHead title={t.orders} icon={ShoppingBag}/>{orders.isPending?<LoadingRows label={t.loading}/>:orders.error?<SectionState title={t.unavailable} kind="error"><Button onClick={()=>void orders.refetch()}>{t.reload}</Button></SectionState>:orders.data?.items.length?<AnimatedList className="checkout-orders" items={orders.data.items} getKey={order=>order.id}>{order=><article className="checkout-order-row"><ButtonLink variant="ghost" href={`/${locale}/checkout/${order.id}`}><BidiReference>{formatQuotedMoney(order.total_minor,order.currency,locale)}</BidiReference></ButtonLink><BidiReference>{order.id}</BidiReference></article>}</AnimatedList>:<SectionState title={t.noOrders} icon={ShoppingBag}/>}</Card></div></>;
}
