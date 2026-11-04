'use client';
import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authenticatedRequest, useSession } from '@/features/identity/session';
import { AnimatedList, BidiReference, Button, Card, Input } from '@beirut-time/ui';
import { History, ReceiptText } from 'lucide-react';
import { Select } from '@beirut-time/ui';
import { CardHead, LoadingRows, Notice, SectionState } from '@beirut-time/ui';
import type { Currency, Quote, QuoteInput } from '@contracts/contracts-pricing/quotes';
import { command, Desk, Failure, PrivateGate, useCopy } from './shared';
import { money, parseMinor, parseRevision, validReference } from './money';
const base='/api/web/v1/pricing/v1/quotes';

export function QuoteFees({quote}:{quote:Quote}) {
  const {locale,t}=useCopy();
  return <><Notice>{t.sample}</Notice>{quote.source_verified&&<p className="l07-muted">{t.verifiedSource}</p>}<dl className="l07-fees">{(['price_minor','buyer_fee_minor','shipping_minor','tax_minor','payable_minor','seller_commission_minor','seller_net_minor'] as const).map((field,index)=><div key={field} className={field==='payable_minor'?'l07-total':''}><dt>{[t.base,t.buyerFee,t.shipping,t.tax,t.payable,t.sellerCommission,t.sellerNet][index]}</dt><dd><BidiReference>{money(quote[field],quote.currency,locale)}</BidiReference></dd></div>)}</dl><p className="l07-muted">{t.commissionBasis}</p><p className="l07-muted">{t.expires}: <time dateTime={quote.expires_at}>{new Date(quote.expires_at).toLocaleString(locale==='ar'?'ar-LB':'en-GB',{timeZone:'Asia/Beirut'})}</time></p><p className="l07-reference"><BidiReference>{quote.id}</BidiReference> · {t.revision} {quote.revision}</p></>;
}
function Prices({initialId}:{initialId?:string}) {
  const session=useSession()!,{locale,t}=useCopy(),client=useQueryClient();
  const scope=session.access_fingerprint;
  const [subject,setSubject]=useState(''),[revision,setRevision]=useState('1'),[amount,setAmount]=useState('5000.00'),[currency,setCurrency]=useState<Currency>('USD'),[purpose,setPurpose]=useState<QuoteInput['purpose']>('purchase'),[source,setSource]=useState<NonNullable<QuoteInput['source']>>('sample');
  const [selected,setSelected]=useState<string|undefined>(initialId),[localError,setLocalError]=useState<unknown>(null);
  const operation=useRef({payload:'',key:''}),reviewKeys=useRef(new Map<string,string>());
  const history=useQuery({queryKey:['l07',scope,'quotes'],queryFn:({signal})=>authenticatedRequest<{items:Quote[]}>(base,{signal})});
  const detail=useQuery({queryKey:['l07',scope,'quote',selected],queryFn:({signal})=>authenticatedRequest<Quote>(`${base}/${selected}`,{signal}),enabled:!!selected});
  const create=useMutation({mutationFn:async(body:QuoteInput)=>{
    const payload=JSON.stringify(body); if(operation.current.payload!==payload) operation.current={payload,key:crypto.randomUUID()};
    return authenticatedRequest<Quote>(base,command(body,operation.current.key));
  },onSuccess:quote=>{setSelected(quote.id);client.setQueryData(['l07',scope,'quote',quote.id],quote);void client.invalidateQueries({queryKey:['l07',scope,'quotes']});}});
  const review=useMutation({mutationFn:async(quote:Quote)=>{
    if(!reviewKeys.current.has(quote.id)) reviewKeys.current.set(quote.id,crypto.randomUUID());
    const body:QuoteInput&{quote_revision:number;payable_minor:number}={subject_id:quote.subject_id,subject_revision:quote.subject_revision,purpose:quote.purpose,currency:quote.currency,price_minor:quote.price_minor,schedule_id:quote.schedule_id,source:quote.source??'sample',quote_revision:quote.revision,payable_minor:quote.payable_minor};
    return authenticatedRequest<Quote>(`${base}/${quote.id}/review`,command(body,reviewKeys.current.get(quote.id)!));
  },onSuccess:quote=>{client.setQueryData(['l07',scope,'quote',quote.id],quote);void client.invalidateQueries({queryKey:['l07',scope,'quotes']});}});
  const submit=(event:React.FormEvent)=>{event.preventDefault();setLocalError(null);try {if(!validReference(subject)) throw new Error('invalidReference');create.mutate({subject_id:subject,subject_revision:parseRevision(revision),price_minor:parseMinor(amount,currency),currency,purpose,source,schedule_id:'sample-v1'});}catch(error){setLocalError(error);}};
  return <><Notice>{t.sampleInfo}</Notice><div className="l07-grid"><Card className="l07-stack"><CardHead title={t.createQuote} icon={ReceiptText}/><form className="l07-form" onSubmit={submit}><label>{t.source}<Select aria-label={t.source} value={source} onValueChange={next=>{const value=next as NonNullable<QuoteInput['source']>;setSource(value);if(value==='listing')setPurpose('purchase');}} options={[{value:'sample',label:t.sampleSource},{value:'listing',label:t.listingSource}]}/></label><label>{t.subject}<Input name="subject" maxLength={36} required value={subject} onChange={e=>setSubject(e.target.value)} dir="ltr" autoComplete="off" /></label><div className="l07-pair"><label>{t.subjectRevision}<Input name="subject_revision" maxLength={9} required inputMode="numeric" value={revision} onChange={e=>setRevision(e.target.value)}/></label><label>{t.purpose}<Select aria-label={t.purpose} value={purpose} onValueChange={next=>{const value=next as QuoteInput['purpose'];setPurpose(value);if(value!=='purchase')setSource('sample');}} options={(['purchase','offer','bid','business_quote'] as const).map(p=>({value:p,label:t[p]}))}/></label></div><div className="l07-pair"><label>{t.price}<Input name="price" maxLength={20} required inputMode="decimal" value={amount} onChange={e=>setAmount(e.target.value)} dir="ltr"/></label><label>{t.currency}<Select aria-label={t.currency} value={currency} onValueChange={value=>setCurrency(value as Currency)} options={[{value:'USD',label:'USD'},{value:'LBP',label:'LBP'}]}/></label></div><Button chonk size="sm" disabled={create.isPending} type="submit">{create.isPending?t.working:t.createQuote}</Button></form><p className="l07-muted">{t.notBinding}</p><Failure error={localError||create.error}/></Card><Card className="l07-stack"><CardHead title={t.viewQuote} icon={ReceiptText}/>{detail.data?<><QuoteFees quote={detail.data}/><p className="l07-muted">{t.notBinding}</p>{detail.data.reviewed_at?<p role="status">{t.reviewed}</p>:<Button chonk size="sm" disabled={review.isPending} onClick={()=>review.mutate(detail.data!)}>{review.isPending?t.working:t.reviewQuote}</Button>}<Failure error={review.error}/></>:detail.isFetching?<LoadingRows label={t.loading}/>:<SectionState title={t.quoteMissing} icon={ReceiptText}/>}<Failure error={detail.error} retry={()=>void detail.refetch()}/></Card></div><section className="l07-stack"><CardHead title={t.history} icon={History}/>{history.isPending&&<LoadingRows label={t.loading}/>}<Failure error={history.error} retry={()=>void history.refetch()}/><AnimatedList className="l07-history" items={history.data?.items??[]} getKey={quote=>quote.id} empty={history.isSuccess?<Card><SectionState title={t.emptyQuotes} icon={ReceiptText}/></Card>:undefined}>{quote=><Card className="l07-actions"><Button chonk size="sm" variant="outline" onClick={()=>{setSelected(quote.id);review.reset();}}>{t.viewQuote} · <BidiReference>{money(quote.payable_minor,quote.currency,locale)}</BidiReference></Button><small>{t.sample}</small><span className="l07-reference"><BidiReference>{quote.id}</BidiReference></span></Card>}</AnimatedList></section></>;
}
export default function PricingPage({initialId}:{initialId?:string}) {
  const {t}=useCopy(),session=useSession();
  return <Desk title={t.pricesTitle} intro={t.pricesIntro} current="prices"><PrivateGate next="/prices">{session&&<Prices key={session.access_fingerprint} initialId={initialId}/>}</PrivateGate></Desk>;
}
