'use client';
import {useEffect,useRef,useState} from 'react';
import {Button,ButtonLink,Card,Checkbox,Fold,Input,RowSkeleton,State,StatusBadge} from '@beirut-time/ui/foundation';
import type {SlotContext} from '@/registry-types';
import {ApiError,request} from '@/lib/api/client';
import {definePageRead} from '@/lib/page-speed/definition';
import {usePageRead} from '@/lib/page-speed/read';
import {useSession,useSessionState,refreshSession,signInHref} from '@/features/identity/session';
import {listingAuctionRead} from '@/features/proxy-bid/listing-auction-read';
import {previewMaximum,reviewMaximum,type MaximumQuote} from '@/features/proxy-bid/maximum-api';
import {auctionBase,command,displayMinor,errorCopy,minor,type Outcome} from './api';
import en from './en.json';
import ar from './ar.json';
import {useOperationScope} from './operation-scope';

type History={items:{sequence:number;bidder:string;amount_minor:number;received_at:string}[]};
const bidHistory=definePageRead({
  key:(auctionId:string,revision:number)=>['auction-bid-slot-history',auctionId,revision],
  fresh:1000,warm:'safe',
  ask:(signal,auctionId:string,_revision:number)=>request<History>(`${auctionBase}/auctions/${encodeURIComponent(auctionId)}/history?limit=10`,{signal}),
});

export default function BidSlot(props:SlotContext) {
  const session=useSession(),sessionState=useSessionState();
  return <BidView key={`${session?.access_fingerprint??'signed-out'}:${props.resourceId??''}`} resourceId={props.resourceId}
    locale={props.locale} session={session} sessionState={sessionState}/>;
}

function BidView({resourceId,locale,session,sessionState}:SlotContext&{session:ReturnType<typeof useSession>;sessionState:ReturnType<typeof useSessionState>}) {
  const owner=session?.access_fingerprint,t=locale==='ar'?ar:en,operationScope=useOperationScope();
  const lots=usePageRead(resourceId?listingAuctionRead(resourceId):null);
  const {refetch:refreshLots}=lots;
  // This mounted slot owns the cadence; the maximum shortcut observes this same answer.
  useEffect(()=>{
    if(!resourceId) return;
    const timer=setInterval(()=>void refreshLots({cancelRefetch:false}),1000);
    return ()=>clearInterval(timer);
  },[resourceId,refreshLots]);
  const lot=lots.data?.items[0];
  const held=lot&&'mode' in lot&&!!lot.mode&&lot.mode!=='bidding';
  const history=usePageRead(lot?bidHistory(lot.id,lot.revision):null);
  const [rules,setRules]=useState(false),[amount,setAmount]=useState(''),[savedQuote,setQuote]=useState<MaximumQuote|null>(null);
  const quote=savedQuote?.auction_revision===lot?.revision&&savedQuote?.binding.subject_id===lot?.id?savedQuote:null;
  const [reviewed,setReviewed]=useState(false),[message,setMessage]=useState(''),[pending,setPending]=useState(false),[uncertain,setUncertain]=useState(false),[outcome,setOutcome]=useState<Outcome|null>(null);
  const previewKey=useRef<{binding:string;key:string}|null>(null);
  const attempt=useRef<{auction:string;key:string;reviewKey:string;body:{amount_minor:number;fee_quote_id:string;expected_revision:number};quote:MaximumQuote;phase:'review'|'bid'}|null>(null);
  async function preview() {
    if(!lot||lot.currency!=='USD'||!session||!owner||pending||uncertain) return;
    const scope=operationScope();setPending(true);setQuote(null);setReviewed(false);
    try {
      const cents=minor(amount),binding=`${lot.id}:${lot.revision}:${cents}`;
      if(previewKey.current?.binding!==binding) previewKey.current={binding,key:crypto.randomUUID()};
      const result=await previewMaximum(lot,cents,{subjectId:session.principal.actor.subject_id,accessFingerprint:owner},scope.controller.signal,previewKey.current.key);
      if(!scope.active) return;
      setQuote(result);setMessage('');
    } catch(error) {if(scope.active) setMessage(errorCopy(error,t));}
    finally {if(scope.active) setPending(false);}
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault();
    if(!owner||pending||(!attempt.current&&(!lot||!quote||!reviewed||lot.status!=='live'||held))) return;
    const scope=operationScope();setPending(true);setMessage(t.pending);
    try {
      if(!attempt.current&&lot&&quote) attempt.current={auction:lot.id,key:crypto.randomUUID(),reviewKey:crypto.randomUUID(),
        body:{amount_minor:quote.amount_minor,fee_quote_id:quote.fee_quote_id,expected_revision:lot.revision},quote,phase:'review'};
      const current=attempt.current;
      if(!current) return;
      if(current.phase==='review') {
        await reviewMaximum(current.quote,current.reviewKey,scope.controller.signal);
        if(!scope.active) return;
        current.phase='bid';
      }
      const result=await command(`/auctions/${current.auction}/bids`,current.body,current.key,scope.controller.signal,owner);
      if(!scope.active) return;
      if(!result||result.auction_id!==current.auction||typeof result.code!=='string'||!result.code||
        !Number.isSafeInteger(result.revision)||result.revision<1||
        !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(result.operation_id)||
        (result.status!=='denied'&&(result.status!=='succeeded'||result.code!=='bid_accepted'||result.revision<=current.body.expected_revision))) {
        setUncertain(true);return;
      }
      setOutcome(result);setUncertain(false);setMessage(result.status==='succeeded'?t.accepted:
        result.code==='bid_permission_required'?t.denied:(t[result.code as keyof typeof t]??t.notConfirmed));
      attempt.current=null;previewKey.current=null;setQuote(null);setReviewed(false);void refreshLots();
    } catch(error) {
      if(!scope.active) return;
      const unknown=attempt.current?.phase==='bid'||!(error instanceof ApiError)||error.status>=500;
      setUncertain(unknown);
      if(!unknown) {
        attempt.current=null;previewKey.current=null;setQuote(null);setReviewed(false);
      }
      setMessage(errorCopy(error,t));
    } finally {if(scope.active) setPending(false);}
  }
  if(!resourceId) return null;
  if(lots.isError) return <Card className="auction-feature"><State kind="error" title={errorCopy(lots.error,t)} body={t.retry}><Button onClick={()=>void refreshLots()}>{t.retry}</Button></State></Card>;
  if(!lot) return lots.isPending?<Card className="auction-feature"><State kind="loading" title={t.pending} body={t.bid}><RowSkeleton/></State></Card>:null;
  const money=(value:number)=>displayMinor(value,lot.currency,locale);
  return <Card className="auction-feature auction-bid-panel"><div className="auction-row"><h2>{t.bid}</h2><StatusBadge tone={held?'warning':lot.status==='live'?'success':'neutral'}>{held?t.heldStatus:t[lot.status]}</StatusBadge></div>
    <div className="auction-price"><span>{t.current}</span><strong>{money(lot.current_minor||lot.opening_minor)}</strong><small>{t.next}: {money(lot.next_minimum_minor)}</small></div>
    <Fold open={rules} onOpenChange={setRules} label={t.rules}><dl><div><dt>{t.startsUtc}</dt><dd><bdi>{lot.starts_at}</bdi></dd></div><div><dt>{t.endsUtc}</dt><dd><bdi>{lot.ends_at}</bdi></dd></div><div><dt>{t.server}</dt><dd><bdi>{lot.server_time}</bdi></dd></div></dl>
      <p>{lot.reserve_set?t.reserveSet:t.reserveNone} · {t.extension}</p><p>{t.highValue} {money(lot.high_value_minor)}</p>
      <ul>{lot.increment_bands.map(b=><li key={b.from_minor}>{money(b.from_minor)} + {money(b.step_minor)}</li>)}</ul></Fold>
    {!session?sessionState==='restoring'?<State kind="loading" title={t.pending} body={t.bid}/>:sessionState==='unavailable'?<State kind="error" title={t.unavailable} body={t.retry}><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></State>:<State title={t.signinBuyer} body={t.bid}><ButtonLink href={signInHref(`/watches/${resourceId}`,locale)}>{t.signin}</ButtonLink></State>:
      held&&!uncertain?<p role="status">{t.saleHeld}</p>:<form onSubmit={submit} className="auction-bid-form">
        <Input label={t.amount} value={amount} inputMode="decimal" required disabled={pending||uncertain} onValueChange={value=>{setAmount(value);setQuote(null);setReviewed(false);}}/>
        <Button type="button" disabled={pending||uncertain||!amount||lot.status!=='live'} onClick={()=>void preview()}>{t.fees}</Button>
        {quote&&<div className="auction-fee-preview"><p className="muted">{t.samplePolicy}</p><dl><div><dt>{t.buyerFee}</dt><dd>{money(quote.buyer_fee_minor)}</dd></div><div><dt>{t.shipping}</dt><dd>{money(0)}</dd></div><div><dt>{t.tax}</dt><dd>{money(0)}</dd></div><div><dt>{t.total}</dt><dd>{money(quote.total_minor)}</dd></div></dl>
          <Checkbox className="auction-check" label={t.confirmFees} checked={reviewed} onCheckedChange={setReviewed}/></div>}
        <Button type="submit" disabled={pending||(!uncertain&&(!reviewed||!quote||lot.status!=='live'))}>{uncertain?t.retry:t.bid}</Button></form>}
    <p role="status" aria-live="polite">{message}</p>{outcome&&<p className="muted">{t.record}: <bdi>{outcome.operation_id}</bdi>
      {outcome.status==='succeeded'&&outcome.accepted_sequence!==undefined&&<> · {outcome.accepted_sequence}</>}</p>}
    <h3>{t.history}</h3>{history.isError?<p>{t.unavailable}</p>:history.isPending?<RowSkeleton/>:!history.data?.items.length?<p className="muted">{t.noBids}</p>:<ol className="auction-history">{history.data.items.map(b=><li key={b.sequence}><bdi>#{b.sequence} · {b.bidder}</bdi><strong>{money(b.amount_minor)}</strong><time dateTime={b.received_at}><bdi>{b.received_at}</bdi></time></li>)}</ol>}
  </Card>;
}
