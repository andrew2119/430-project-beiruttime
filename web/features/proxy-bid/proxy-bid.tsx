'use client';
import {normalizeDigits} from '@beirut-time/i18n';
import {listingAuctionRead} from './listing-auction-read';
import type {Auction} from '@/features/auction-management/api';
import {useEffect,useEffectEvent,useRef,useState} from 'react';
import {usePageRead} from '@/lib/page-speed/read';
import {AnswerArrival} from '@/lib/page-speed/arrival';
import {useLocale} from '@/shell/locale-context';
import {PageFrame,PageHeader} from '@/shell/foundation/page';
import {definePageRead} from '@/lib/page-speed/definition';
import {Button,ButtonLink,Card,Fold,Input,State,RowSkeleton,formatNumber} from '@beirut-time/ui/foundation';
import type {SlotContext} from '@/registry-types';
import type {BidHistory,AuctionSnapshot} from '@contracts/contracts-auction/core';
import {ApiError,request} from '@/lib/api/client';
import {refreshSession,signInHref,useBuyerSession} from './session';
import {earlierMaximumCommand,lookupMaximum,lookupMaximumV1,readOwnMaximum,type OwnMaximum,MAX_QUOTE_MINOR,previewMaximum,reviewMaximum,sendMaximum,recoverLegacyMaximum,replayEarlierMaximum,restoreMaximumIntent,restoreMaximumReview,type MaximumReference,type MaximumIntent,type MaximumQuote} from './maximum-api';
import {formatMinor,parseMaximum} from './money';
import {BuyerLanguageControl} from './buyer-language';
import {EarlierBids} from './earlier-bids';
import {readPendingMaximum,retainPendingMaximum,retainPendingReview,settlePendingMaximum} from './pending-maximum';
import {auctionTiming,observeAuctionEnd} from './auction-time';
import en from './en.json';
import ar from './ar.json';

const MAX_AUCTION_MINOR=9_000_000_000_000_000;
const PRIVATE_READ_REFRESH_MS=5000;
// Identity and Auction each have a 1200 ms gateway budget. Leave room for
// forwarding and response decoding after both sequential calls.
const PRIVATE_READ_DEADLINE_MS=3000;

function feeReviewRejection(error:ApiError) {
  if(error.status===404&&error.code==='quote_not_found') return 'quoteMissing';
  if(error.status===409) {
    if(error.code==='quote_expired') return 'quoteExpired';
    if(['quote_binding_mismatch','already_reviewed','idempotency_conflict'].includes(error.code)) return 'stale';
  }
  if([400,404,422].includes(error.status)&&error.code==='review_denied' ||
    error.status===422&&error.code==='validation_error') return 'denied';
  return null;
}

type FormProps={recoveryScope?:string;highValueMinor?:number;onRecoveryChange?:(pending:boolean)=>void;snapshot?:AuctionSnapshot;lifecycle?:'live'|'scheduled'|'ended'|'unavailable'|'replaced'|'other-auction'|'exhausted'|'held';auctionId:string;revision:number;currency:'USD'|'LBP';locale:'en'|'ar';onRefresh:()=>void;signInNext?:string;getQuote?:(amount:number,signal:AbortSignal,key:string)=>Promise<MaximumQuote>};
export function MaximumForm(props:FormProps) {
  const session=useBuyerSession();
  return <MaximumFormForBuyer key={`${session.fingerprint}:${props.auctionId}`}
    recoveryScope={props.recoveryScope} auctionId={props.auctionId} revision={props.revision} currency={props.currency} locale={props.locale}
    snapshot={props.snapshot} highValueMinor={props.highValueMinor} lifecycle={props.lifecycle} signInNext={props.signInNext}
    getQuote={props.getQuote} onRefresh={props.onRefresh} onRecoveryChange={props.onRecoveryChange} session={session}/>;
}
function MaximumFormForBuyer({onRecoveryChange,snapshot,highValueMinor,lifecycle='live',auctionId,recoveryScope=auctionId,revision,currency,locale,onRefresh,getQuote,signInNext,session}:FormProps&{session:ReturnType<typeof useBuyerSession>}) {
  const t=locale==='ar'?ar:en;
  const [value,setValue]=useState(''),[savedQuote,setQuote]=useState<MaximumQuote|null>(null);
  const quote=savedQuote?.auction_revision===revision?savedQuote:null;
  const [state,setState]=useState<'idle'|'recoveryUnavailable'|'quoting'|'quoted'|'quoteUnavailable'|'quoteExpired'|'quoteMissing'|'sending'|'acknowledged'|'invalidAmount'|'denied'|'stale'|'uncertain'|'offline'>('idle');
  const [operationReference,setOperationReference]=useState<string|null>(null);
  const [resolved,setResolved]=useState<{key:string;watchId:string|null;state:'accepted'|'denied'|'stale'|'feeReviewed'}|null>(null);
  const [reviewReference,setReviewReference]=useState<string|null>(null);
  const intent=useRef<MaximumReference|MaximumIntent|null>(null),generation=useRef(0),cancellation=useRef<AbortController|null>(null);
  const submitted=useRef(false);
  const previewIntent=useRef<{amount:number;revision:number;key:string}|null>(null);
  const review=useRef<{key:string;quote?:MaximumQuote;uncertain:boolean}|null>(null);
  const allowed=Boolean(session.state==='authenticated'&&session.signedIn&&session.subjectId&&session.fingerprint&&!session.organizationId&&session.roles.includes('buyer'));
  useEffect(()=>()=>{generation.current++;cancellation.current?.abort();intent.current=null;review.current=null;},[]);
  const [recoveryRestored,setRecoveryReady]=useState(false),[recoveryAttempt,retryRecovery]=useState(0);
  const restorePending=useEffectEvent(()=>{
    let pending;
    try {
      pending=readPendingMaximum(recoveryScope,session.fingerprint!,session.subjectId!,id=>id===auctionId);
    } catch {
      setRecoveryReady(false);setState('recoveryUnavailable');
      return;
    }
    if(pending&&!intent.current) {
      intent.current=pending.intent;
      review.current=pending.review&&{...pending.review,uncertain:true};
      submitted.current=pending.review===null;
      setReviewReference(pending.review?.key??null);
      setOperationReference(submitted.current?pending.intent.key:null);
      setState('uncertain');
      onRecoveryChange?.(true);
    }
    setRecoveryReady(true);
    setState(previous=>previous==='recoveryUnavailable'?'idle':previous);
  });
  useEffect(()=>{
    if(!allowed) return;
    let current=true;
    void Promise.resolve().then(()=>{if(current) restorePending();});
    return ()=>{current=false;};
  },[allowed,auctionId,recoveryScope,session.fingerprint,session.subjectId,recoveryAttempt]);
  const [stored,setStored]=useState<OwnMaximum|null>(null);
  const [readState,setReadState]=useState<'loading'|'available'|'unavailable'|'denied'>('loading');
  const [readAttempt,retryRead]=useState(0),[readRevision,setReadRevision]=useState<number|null>(null);
  const [readDenied,setReadDenied]=useState(false);
  const [legacy,setLegacy]=useState(false);
  const [previouslyAllowed,setPreviouslyAllowed]=useState(allowed);
  if(previouslyAllowed!==allowed) {
    setPreviouslyAllowed(allowed);
    if(!allowed) {
      setStored(null);setReadRevision(null);setReadState('loading');setLegacy(false);
    }
  }
  // Recovery is bound to the original command. A newer current read can
  // authorize recovery even when the displayed auction snapshot is behind.
  const recoveryReady=allowed&&!readDenied&&readState==='available'&&readRevision!==null&&readRevision>=revision;
  const canReadReceipt=(watchId:string|null)=>recoveryReady&&(watchId===null||!legacy&&stored?.watch_id===watchId);
  const commandRecoveryReady=intent.current!==null&&canReadReceipt(intent.current.watch_id);
  const readReady=recoveryReady&&stored!==null&&readRevision===revision;
  const quoteMinimum=snapshot?.id===auctionId
    ? readReady&&stored?.standing==='leading'&&snapshot.accepted_sequence>0
      ? snapshot.current_minor
      : verifiedMinimum(snapshot)
    : null;
  const previewLimitReached=(quoteMinimum!==null&&quoteMinimum>MAX_QUOTE_MINOR)||
    (readReady&&(stored?.amount_minor??0)>=MAX_QUOTE_MINOR);
  const privacy=legacy?t.legacyPrivacy:t.privacy;
  const admission=useRef({allowed,lifecycle,revision,readReady,previewLimitReached,commandRecoveryReady,watchId:stored?.watch_id});
  useEffect(()=>{admission.current={allowed,lifecycle,revision,readReady,previewLimitReached,commandRecoveryReady,watchId:stored?.watch_id};},[allowed,lifecycle,revision,readReady,previewLimitReached,commandRecoveryReady,stored?.watch_id]);

  function resetReview(keepAuction=false) {
    if(intent.current) settlePendingMaximum(recoveryScope,intent.current,'review');
    intent.current=null;review.current=null;setReviewReference(null);setQuote(null);
    if(!keepAuction) onRecoveryChange?.(false);
  }
  function clearDeniedAccess(reviewRequestDenied=false) {
    generation.current++;
    cancellation.current?.abort();cancellation.current=null;
    const pendingReview=review.current;
    // Denial of a replay does not settle the original review. An independent
    // denial may also have interrupted an in-flight review before its reply.
    const keepReview=pendingReview!==null&&(!reviewRequestDenied||pendingReview.uncertain);
    if(keepReview) pendingReview.uncertain=true;
    setStored(null);setQuote(null);setValue('');
    if(!submitted.current&&!keepReview) {
      resetReview(resolved!==null);setOperationReference(null);
    }
    setReadRevision(null);setReadState('denied');setReadDenied(true);setLegacy(false);
    setState(submitted.current||keepReview?'uncertain':'denied');
  }
  const denyDuringRead=useEffectEvent(clearDeniedAccess);
  useEffect(()=>{
    if(!allowed||!session.subjectId||!session.fingerprint) return;
    let stopped=false;
    let timer:ReturnType<typeof setTimeout>|undefined;
    let controller:AbortController|undefined;
    async function recheck(subjectId:string,accessFingerprint:string) {
      const requestController=new AbortController();
      controller=requestController;
      const epoch=generation.current;
      let deadline:ReturnType<typeof setTimeout>|undefined;
      const expired=new Promise<never>((_,reject)=>{
        deadline=setTimeout(()=>{
          requestController.abort();
          reject(new ApiError(503,'private_maximum_timeout',''));
        },PRIVATE_READ_DEADLINE_MS);
      });
      try {
        const owner={subjectId,accessFingerprint};
        const result=await Promise.race([readOwnMaximum(auctionId,owner,requestController.signal),expired]);
        if(stopped||epoch!==generation.current) return;
        if(result.schema_version===1) {
          setStored(null);setReadRevision(result.revision);setReadDenied(false);setReadState('available');setLegacy(true);
          return;
        }
        setLegacy(false);
        if(requestController.signal.aborted||result.revision<revision) throw new ApiError(503,'stale_private_maximum','');
        setStored(result);setReadRevision(result.revision);setReadDenied(false);setReadState('available');
      } catch(error) {
        if(stopped||epoch!==generation.current) return;
        if(error instanceof ApiError&&[401,403].includes(error.status)) denyDuringRead();
        else {setStored(null);setReadRevision(null);setReadState('unavailable');}
      } finally {
        clearTimeout(deadline);
        if(!stopped) timer=setTimeout(()=>void recheck(subjectId,accessFingerprint),PRIVATE_READ_REFRESH_MS);
      }
    }
    void recheck(session.subjectId,session.fingerprint);
    return ()=>{stopped=true;controller?.abort();clearTimeout(timer);};
  },[allowed,auctionId,revision,session.subjectId,session.fingerprint,readAttempt]);
  function handleSubmissionFailure(error:unknown) {
    if(error instanceof ApiError) {
      if([401,403].includes(error.status)) {
        clearDeniedAccess(!submitted.current);
        return;
      }
      const rejection=feeReviewRejection(error);
      if(!submitted.current&&rejection) {
        // Keep the original auction mounted until the buyer sees the decision.
        resetReview(true);
        setState(rejection);
        return;
      }
    }
    if(review.current) review.current.uncertain=true;
    setState('uncertain');
  }
  async function submit() {
    if(!recoveryRestored||previewLimitReached||resolved||submitted.current||lifecycle!=='live'||!allowed||!readReady||(intent.current&&(!review.current||!quote))||state==='sending'||state==='quoting'||!session.fingerprint||!getQuote) return;
    if(navigator.onLine===false) {setState(intent.current?'uncertain':'offline');return;}
    const amount=parseMaximum(value);
    if(amount===null) {setState('invalidAmount');return;}
    const epoch=generation.current;
    cancellation.current??=new AbortController();
    const signal=cancellation.current.signal;
    if(!quote&&!intent.current) {
      onRecoveryChange?.(false);
      if(previewIntent.current?.amount!==amount||previewIntent.current.revision!==revision) {
        previewIntent.current={amount,revision,key:crypto.randomUUID()};
      }
      setState('quoting');
      try {
        const preview=await getQuote(amount,signal,previewIntent.current.key);
        if(epoch!==generation.current) return;
        if(preview.amount_minor!==amount||preview.auction_revision!==revision||!Number.isSafeInteger(preview.buyer_fee_minor)||preview.buyer_fee_minor<0||
          !Number.isSafeInteger(preview.total_minor)||preview.total_minor<amount||preview.currency!==currency||
          !preview.fee_quote_id||!Number.isFinite(Date.parse(preview.expires_at))) throw new Error('invalid_quote');
        previewIntent.current=null;setQuote(preview);setState('quoted');
      } catch(error) {
        if(epoch!==generation.current) return;
        if(error instanceof ApiError&&[401,403].includes(error.status)) clearDeniedAccess();
        else if(error instanceof ApiError&&error.code==='quote_expired') {previewIntent.current=null;setState('quoteExpired');}
        else setState(error instanceof ApiError&&error.status===422?'invalidAmount':'quoteUnavailable');
      }
      return;
    }
    // An uncertain operation always retries the exact original body/key, even
    // after quote expiry. Only the authoritative runtime can reconcile it.
    if(!session.subjectId||(intent.current&&intent.current.watch_id!==(stored?.watch_id??null))) return;
    const pending:MaximumIntent=intent.current&&'amount_minor' in intent.current?intent.current:{key:crypto.randomUUID(),amount_minor:amount,fee_quote_id:quote!.fee_quote_id,revision,owner:session.fingerprint,
      actor_id:session.subjectId,watch_id:stored?.watch_id??null,quote_revision:quote!.quote_revision,policy_revision:quote!.policy_revision};
    intent.current=pending;
    review.current??={key:crypto.randomUUID(),quote:quote!,uncertain:false};
    const acknowledgement=review.current;
    if(!acknowledgement.quote) return;
    let retained=false;
    try {
      retained=retainPendingReview(recoveryScope,auctionId,pending,acknowledgement);
    } catch {
      setState('recoveryUnavailable');
    }
    if(!retained) {
      intent.current=null;review.current=null;
      setRecoveryReady(false);
      retryRecovery(attempt=>attempt+1);
      return;
    }
    onRecoveryChange?.(true);
    setState('sending');
    try {
      setReviewReference(acknowledgement.key);
      await reviewMaximum(acknowledgement.quote,acknowledgement.key,signal,session.confirmMissingQuote);
      if(epoch!==generation.current) return;
      if(!submitted.current&&(!admission.current.allowed||admission.current.lifecycle!=='live'||!admission.current.readReady||admission.current.previewLimitReached||
          admission.current.revision!==pending.revision||(admission.current.watchId??null)!==pending.watch_id)) {
        resetReview(true);
        setResolved({key:acknowledgement.key,watchId:pending.watch_id,state:'feeReviewed'});
        setState('idle');
        return;
      }
      let persisted=false;
      try {
        persisted=retainPendingMaximum(recoveryScope,auctionId,pending);
      } catch {
        acknowledgement.uncertain=true;
        setState('recoveryUnavailable');
        return;
      }
      if(!persisted) {
        if(submitted.current) return;
        intent.current=null;
        setState('uncertain');
        setRecoveryReady(false);
        retryRecovery(attempt=>attempt+1);
        return;
      }
      review.current=null;
      setReviewReference(null);
      submitted.current=true;
      setOperationReference(pending.key);
      const outcome=(await sendMaximum(auctionId,pending,signal)).state;
      if(epoch!==generation.current||pending.owner!==session.fingerprint) return;
      if(outcome==='pending') setState('uncertain');
      else finishBid(pending,outcome);
    } catch(error) {
      if(epoch!==generation.current) return;
      handleSubmissionFailure(error);
    }
  }
  function finishBid(pending:MaximumReference,outcome:'accepted'|'denied'|'stale') {
    settlePendingMaximum(recoveryScope,pending,'bid');
    submitted.current=false;
    resetReview(true);
    setOperationReference(null);
    setResolved({key:pending.key,watchId:pending.watch_id,state:outcome});
    if(outcome==='accepted') setValue('');
    setState('idle');
    onRefresh();
  }

  async function reconcile(replay=false) {
    const pending=intent.current;
    if(!commandRecoveryReady||!pending||!submitted.current||state==='sending') return;
    const epoch=generation.current;
    cancellation.current??=new AbortController();
    setState('sending');
    try {
      const signal=cancellation.current.signal;
      let outcome:'accepted'|'denied'|'stale'|'pending';
      if(pending.watch_id===null&&'amount_minor' in pending) {
        outcome=replay?await recoverLegacyMaximum(auctionId,pending,signal):
          await lookupMaximumV1(auctionId,pending.key,earlierMaximumCommand(pending),pending.owner,signal);
      } else if(replay) {
        if('amount_minor' in pending) {
          outcome=(await sendMaximum(auctionId,pending,signal)).state;
        } else {
          const command=await restoreMaximumIntent(auctionId,pending,signal);
          if(epoch!==generation.current) return;
          if(!admission.current.commandRecoveryReady) {setState('uncertain');return;}
          outcome=(await sendMaximum(auctionId,command,signal)).state;
        }
      } else {
        outcome=(await lookupMaximum(auctionId,pending,signal)).state;
      }
      if(epoch!==generation.current) return;
      if(outcome==='pending') {setState('uncertain');return;}
      finishBid(pending,outcome);
    } catch(error) {
      if(epoch!==generation.current) return;
      if(error instanceof ApiError&&[401,403].includes(error.status)) {
        clearDeniedAccess();
      } else setState('uncertain');
    }
  }
  async function recoverReview() {
    const acknowledgement=review.current, original=intent.current;
    if(!commandRecoveryReady||!acknowledgement||!original||submitted.current||state==='sending') return;
    const epoch=generation.current;
    cancellation.current??=new AbortController();
    setState('sending');
    try {
      const signal=cancellation.current.signal;
      let quote=acknowledgement.quote;
      if(!quote) {
        quote=await restoreMaximumReview(auctionId,original,signal,session.confirmMissingQuote);
        if(epoch!==generation.current) return;
        if(!admission.current.commandRecoveryReady) {setState('uncertain');return;}
      }
      await reviewMaximum(quote,acknowledgement.key,signal,session.confirmMissingQuote);
      if(epoch!==generation.current) return;
      // Recover only the fee acknowledgement; a bid requires a separate live action.
      resetReview(true);
      setResolved({key:acknowledgement.key,watchId:original.watch_id,state:'feeReviewed'});
      setState('idle');
    } catch(error) {
      if(epoch!==generation.current) return;
      handleSubmissionFailure(error);
    }
  }
  function continueRecovery() {
    setResolved(null);
    setState('idle');
    setRecoveryReady(false);
    retryRecovery(attempt=>attempt+1);
    onRecoveryChange?.(false);
  }

  const frozen=state==='sending'||state==='uncertain'||state==='quoting';
  const privacyId=`proxy-privacy-${auctionId}`,feedbackId=`proxy-feedback-${auctionId}`,limitId=`proxy-limit-${auctionId}`;
  return <Card className="proxy-panel">{snapshot&&<PublicAuctionFacts key={snapshot.id} auction={snapshot} locale={locale}/>}<h2>{lifecycle==='other-auction'?t.otherAuctionRecovery:t.privateMaximum}</h2><p id={privacyId}>{privacy}</p>
    {lifecycle==='ended'&&<div><p>{t.auctionEnded}</p><ButtonLink href={`/${locale}/buyer?view=won`}>{t.viewResults}</ButtonLink></div>}
    {session.state==='restoring'?<><State title={t.loading} body={t.privacy} kind="loading"/><RowSkeleton/></>:session.state==='unavailable'?<State body={t.retryBody} title={t.unavailable} kind="error"><Button size="sm" onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></State>:!allowed?<State body={t.retryBody} title={session.signedIn?t.accessDenied:t.signIn}>{!session.signedIn&&<ButtonLink href={signInHref(signInNext??'/buyer',locale)}>{t.account}</ButtonLink>}</State>:currency!=='USD'?<State body={t.retryBody} title={t.unavailable} kind="error"/>:<><p>{lifecycle==='replaced'?t.previousAuctionRecovery:lifecycle==='unavailable'?t.unavailable:lifecycle==='scheduled'?t.auctionScheduled:lifecycle==='exhausted'?t.bidRangeExhausted:lifecycle==='held'?t.auctionHeld:''}</p>{lifecycle==='other-auction'&&commandRecoveryReady&&<p>{t.pendingAuction}: <bdi dir="ltr">{auctionId}</bdi></p>}{(lifecycle==='unavailable'||lifecycle==='held')&&<Button type="button" variant="outline" onClick={onRefresh}>{t.retry}</Button>}{reviewReference&&commandRecoveryReady&&<div role="status"><p>{t.reviewReference}: <bdi dir="ltr">{reviewReference}</bdi></p><p>{t.uncertain}</p><Button type="button" disabled={state==='sending'} onClick={()=>void recoverReview()}>{t.recoverReview}</Button></div>}{operationReference&&commandRecoveryReady&&<div role="status"><p>{t.operationReference}: <bdi dir="ltr">{operationReference}</bdi></p><p>{t.uncertain}</p><Button type="button" disabled={state==='sending'} onClick={()=>void reconcile()}>{t.checkOperation}</Button><Button type="button" variant="outline" disabled={state==='sending'} onClick={()=>void reconcile(true)}>{t.retryOperation}</Button></div>}{lifecycle!=='live'&&!operationReference&&commandRecoveryReady&&state!=='idle'&&<p role="status">{t[state]}</p>}<div aria-live="polite">{readState==='denied'?t.accessDenied:readState==='unavailable'?t.maximumUnavailable:!recoveryReady?t.loading:legacy||!readReady?t.maximumUnavailable:
        stored&&<>
          {stored.amount_minor===null?<p>{t.noMaximum}</p>:<>
            <p>{t.storedMaximum}: <bdi dir="ltr">{formatMinor(stored.amount_minor,'USD',locale)}</bdi></p>
            <p>{stored.active?t.activeMaximum:t.inactiveMaximum}</p>
          </>}
          {stored.standing&&<p>{t[stored.standing]}</p>}
        </>}</div>
      {recoveryReady&&lifecycle!=='live'&&(state==='quoteMissing'||state==='quoteExpired'||state==='stale'||state==='denied')&&
        <div role="status">
          <p>{t[state]}</p>
          <Button type="button" onClick={continueRecovery}>{lifecycle==='replaced'?t.continueAuction:t.dismissReceipt}</Button>
        </div>}
      {lifecycle==='live'&&!getQuote&&<State body={t.retryBody} title={t.unavailable} kind="error"/>}
      {state==='recoveryUnavailable'&&<State title={t.unavailable} body={t.recoveryUnavailable}>
        <Button type="button" onClick={()=>retryRecovery(attempt=>attempt+1)}>{t.retry}</Button>
      </State>}
      {legacy&&<State title={t.unavailable} body={t.legacyMaximumUnavailable}/>}
      {resolved&&canReadReceipt(resolved.watchId)&&<div role="status">
        <p>{t.resolvedAuction}: <bdi dir="ltr">{auctionId}</bdi></p>
        <p>{resolved.state==='feeReviewed'?t.reviewReference:t.operationReference}: <bdi dir="ltr">{resolved.key}</bdi></p>
        <p>{t[resolved.state==='accepted'?'acknowledged':resolved.state]}</p>
        <Button type="button" onClick={continueRecovery}>{lifecycle==='other-auction'||resolved.state==='feeReviewed'&&lifecycle!=='replaced'?t.dismissReceipt:t.continueAuction}</Button>
      </div>}
      {(readDenied||legacy||readState==='unavailable')&&<Button type="button" variant="outline" onClick={()=>{setStored(null);setReadState('loading');setReadRevision(null);retryRead(attempt=>attempt+1);}}>{t.retry}</Button>}
      {lifecycle==='live'&&!legacy&&previewLimitReached&&
        <State title={t.previewLimitReached} body={t.previewLimitBody}/>}
      {lifecycle==='live'&&getQuote&&!legacy&&!previewLimitReached&&<form onSubmit={event=>{event.preventDefault();void submit();}}>
      {!readDenied&&<div>
      {highValueMinor!==undefined&&Number.isSafeInteger(highValueMinor)&&highValueMinor>0&&
        <p className="buyer-note">{t.highValueContact} <bdi dir="ltr">{formatMinor(highValueMinor,'USD',locale)}</bdi></p>}
      <p id={limitId} className="buyer-note">{t.quoteLimit}: <bdi dir="ltr">{formatMinor(MAX_QUOTE_MINOR,currency,locale)}</bdi></p>
      <Input id={`maximum-${auctionId}`} inputMode="decimal" autoComplete="off" type="text" value={recoveryReady?value:''} label={`${t.maximumLabel} (USD)`} hint={privacy}
        disabled={frozen||!readReady||!recoveryRestored} onValueChange={next=>{
          if(!readReady) return;
          const trimmed=next.trim();
          const overlong=trimmed.length>18;
          setValue(overlong?'':trimmed);setQuote(null);setState(overlong?'invalidAmount':'idle');
        }}/>
      {readReady&&quote&&<div className="proxy-quote"><p>{t.sampleFeePolicy}</p><p>{t.quoteBasis}</p><dl>
        <div><dt>{t.quoteFee}</dt><dd><bdi dir="ltr">{formatMinor(quote.buyer_fee_minor,quote.currency,locale)}</bdi></dd></div>
        <div><dt>{t.quoteTotal}</dt><dd><bdi dir="ltr">{formatMinor(quote.total_minor,quote.currency,locale)}</bdi></dd></div>
      </dl></div>}
      <p id={feedbackId} role="status" aria-live="polite">{!recoveryReady||state==='idle'||state==='recoveryUnavailable'?'':state==='quoted'&&savedQuote&&!quote?t.stale:t[state]}</p>
      <div className="proxy-actions"><Button size="sm" type="submit" disabled={!recoveryRestored||!readReady||Boolean(resolved)||Boolean(operationReference)||(Boolean(reviewReference)&&!quote)||state==='sending'||state==='quoting'}>{state==='uncertain'?t.retry:state==='sending'?t.sending:quote?t.setMaximum:t.previewMaximum}</Button>
        {state==='stale'&&<Button size="sm" variant="outline" type="button" onClick={onRefresh}>{t.refreshAuction}</Button>}</div>
      </div>}
    </form>}</>}
    {recoveryReady&&<LegacyMaximumReceipt auctionId={auctionId} access={session.fingerprint!} locale={locale} onDenied={clearDeniedAccess}/>}
  </Card>;
}

export function LegacyMaximumReceipt({auctionId,access,locale,onDenied}:{auctionId:string;access:string;onDenied:()=>void;locale:'en'|'ar'}) {
  const t=locale==='ar'?ar:en;
  const [open,setOpen]=useState(false);
  const [reference,setReference]=useState('');
  const [amount,setAmount]=useState('');
  const [quoteId,setQuoteId]=useState('');
  const [sourceRevision,setSourceRevision]=useState('');
  const [status,setStatus]=useState<'idle'|'loading'|'acknowledged'|'denied'|'stale'|'uncertain'|'pending'>('idle');
  const pending=useRef<AbortController|null>(null);
  useEffect(()=>()=>pending.current?.abort(),[]);
  const validReference=reference.length>0&&reference.length<=128&&!/[^A-Za-z0-9_.:-]/.test(reference);
  const cents=parseMaximum(amount);
  const revision=Number(normalizeDigits(sourceRevision.trim()));
  const validCommand=cents!==null&&Number.isSafeInteger(revision)&&revision>0&&
    /^\d+$/.test(normalizeDigits(sourceRevision.trim()))&&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(quoteId.trim());
  async function check(replay=false) {
    if(pending.current||!validReference||!validCommand||cents===null||(replay&&status!=='pending')) return;
    const controller=new AbortController();
    pending.current=controller;
    setStatus('loading');
    try {
      const command={amount_minor:cents,fee_quote_id:quoteId.trim(),expected_revision:revision};
      const state=await (replay?replayEarlierMaximum:lookupMaximumV1)(auctionId,reference,command,access,controller.signal);
      if(!controller.signal.aborted) setStatus(state==='accepted'?'acknowledged':state);
    } catch(error) {
      if(controller.signal.aborted) return;
      if(error instanceof ApiError&&[401,403].includes(error.status)) {
        onDenied();
      } else setStatus('uncertain');
    } finally {
      pending.current=null;
    }
  }
  return <Fold label={t.legacyReceipt} open={open} onOpenChange={setOpen}>
    {open&&<EarlierBids auctionId={auctionId} access={access} locale={locale} onDenied={onDenied}/>}
    <form onSubmit={event=>{event.preventDefault();void check();}}>
      <Input label={t.operationReference} value={reference} autoComplete="off"
        disabled={status==='loading'} onValueChange={value=>{setReference(value);setStatus('idle');}}/>
      <Input label={`${t.maximumLabel} (USD)`} value={amount} inputMode="decimal" autoComplete="off"
        disabled={status==='loading'} onValueChange={value=>{setAmount(value);setStatus('idle');}}/>
      <Input label={t.legacyQuoteReference} value={quoteId} autoComplete="off"
        disabled={status==='loading'} onValueChange={value=>{setQuoteId(value);setStatus('idle');}}/>
      <Input label={t.revision} value={sourceRevision} inputMode="numeric" autoComplete="off"
        disabled={status==='loading'} onValueChange={value=>{setSourceRevision(value);setStatus('idle');}}/>
      <Button type="submit" busy={status==='loading'} disabled={!validReference||!validCommand}>{t.checkOperation}</Button>
      {status==='pending'&&<Button type="button" variant="outline" onClick={()=>void check(true)}>{t.retryOperation}</Button>}
      {status!=='idle'&&<p role="status">{status==='acknowledged'?t.legacyAccepted:t[status==='pending'?'uncertain':status]}</p>}
    </form>
  </Fold>;
}

export default function ProxyBidSlot({resourceId,locale}:SlotContext) {
  const read = usePageRead(resourceId ? listingAuctionRead(resourceId) : null);
  const auction = read.isError ? undefined : currentListingAuction(read.data,resourceId);
  const timing = auction && auctionTiming(auction.starts_at,auction.ends_at,auction.server_time);
  const duration = timing?.status === auction?.status ? timing?.millisecondsUntilEnd : undefined;
  const updated = read.dataUpdatedAt;
  const [endedUpdate,setEndedUpdate]=useState<number|null>(null);
  useEffect(()=>{
    if(duration===undefined) return;
    const age = updated > 0 ? Math.max(0,Date.now()-updated) : 0;
    return observeAuctionEnd(duration,age,()=>setEndedUpdate(updated));
  },[duration,updated]);
  if (!resourceId || !auction || !duration || endedUpdate===updated ||
      ('mode' in auction && auction.mode!==undefined && auction.mode!=='bidding')) return null;

  const t = locale === 'ar' ? ar : en;
  const href = `/${locale}/buyer/auctions/${encodeURIComponent(resourceId)}?auction=${encodeURIComponent(auction.id)}`;
  return <ButtonLink variant="outline" href={href}>{t.privateMaximum}</ButtonLink>;
}

type ListingAuctionRecord = Pick<AuctionSnapshot,'id'|'listing_id'|'currency'|'revision'|'status'>;

function currentListingAuction<T extends ListingAuctionRecord>(page:{items:T[]}|undefined,listingId?:string) {
  const auction=Array.isArray(page?.items)&&page.items.length<=100?page.items[0]:undefined;
  if(auction&&typeof auction.id==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(auction.id)&&
    auction.listing_id===listingId&&auction.currency==='USD'&&Number.isSafeInteger(auction.revision)&&auction.revision>0&&
    ['live','scheduled','ended'].includes(auction.status)) return auction;
}

function isMaskedBidder(value: unknown): value is string {
  return typeof value === 'string' && value.length === 15 && /^Bidder [0-9a-f]{8}$/.test(value);
}

function hasAuctionFacts(auction: AuctionSnapshot) {
  const money = (value: number) => Number.isSafeInteger(value) && value > 0 && value <= MAX_AUCTION_MINOR;
  const noBids = auction.accepted_sequence === 0;
  if (!money(auction.opening_minor)) return false;
  const validPrice = noBids
    ? auction.current_minor === 0 && auction.leader === null
    : Number.isSafeInteger(auction.accepted_sequence) && auction.accepted_sequence > 0 && money(auction.current_minor)
      && auction.current_minor >= auction.opening_minor && isMaskedBidder(auction.leader);
  if (!validPrice) return false;
  return auctionTiming(auction.starts_at,auction.ends_at,auction.server_time)?.status===auction.status;
}

function verifiedMinimum(auction:AuctionSnapshot) {
  const bands=auction.increment_bands;
  if(!Array.isArray(bands)||bands.length<1||bands.length>20||bands[0]?.from_minor!==0) return null;
  let threshold=-1,step=0;
  for(const band of bands) {
    if(!band||!Number.isSafeInteger(band.from_minor)||band.from_minor<=threshold||
      band.from_minor>MAX_AUCTION_MINOR||!Number.isSafeInteger(band.step_minor)||
      band.step_minor<1||band.step_minor>MAX_AUCTION_MINOR) return null;
    threshold=band.from_minor;
    if(threshold<=auction.current_minor) step=band.step_minor;
  }
  const minimum=auction.accepted_sequence===0?auction.opening_minor:auction.current_minor+step;
  return minimum===auction.next_minimum_minor?minimum:null;
}

export function auctionFormLifecycle(auction:Auction) {
  if(auction.status!=='live') return auction.status;
  if(auction.mode!=='bidding') return auction.mode===undefined?'unavailable':'held';
  const minimum=verifiedMinimum(auction);
  if(minimum===null||!Number.isSafeInteger(auction.high_value_minor)||
    auction.high_value_minor<=0||auction.high_value_minor>MAX_AUCTION_MINOR) return 'unavailable';
  return minimum>MAX_AUCTION_MINOR?'exhausted':'live';
}

function BuyerAuctionSlot(props:SlotContext&{auctionId?:string}) {
  const session=useBuyerSession();
  const query=usePageRead(props.resourceId?listingAuctionRead(props.resourceId,props.auctionId):null);
  const {refetch}=query;
  useEffect(()=>{const timer=setInterval(()=>void refetch(),1000);return ()=>clearInterval(timer);},[refetch]);
  return <AuctionMaximumContent key={`${session.fingerprint??'anonymous'}:${props.resourceId}:${props.auctionId??''}`} auctionId={props.auctionId} locale={props.locale} resourceId={props.resourceId} query={query}/>;
}
function AuctionMaximumContent({locale,resourceId,auctionId,query}:SlotContext&{auctionId?:string;query:Pick<ReturnType<typeof usePageRead<{items:AuctionSnapshot[]}>>,'data'|'isPending'|'isError'> & {refetch:()=>unknown}}) {
  const t=locale==='ar'?ar:en,session=useBuyerSession();
  const [retained,setRetained]=useState<AuctionSnapshot|null>(null);
  const [recovering,setRecovering]=useState<AuctionSnapshot|null>(null);
  const [selectedRecovery,setSelectedRecovery]=useState<{auctionId:string;revision:number}|null>(null);
  const [restored,setRestored]=useState<{auctionId:string;revision:number}|null>(null);
  const {fingerprint,subjectId,state:sessionState}=session;
  const [recoveryScan,scanRecovery]=useState(0);
  useEffect(()=>{
    if(!resourceId||sessionState!=='authenticated'||!fingerprint||!subjectId) return;
    let current=true;
    void Promise.resolve().then(()=>{
      if(!current) return;
      try {
        if(auctionId) {
          const selected=readPendingMaximum(resourceId,fingerprint,subjectId,id=>id===auctionId);
          if(selected) setSelectedRecovery({auctionId:selected.auctionId,revision:selected.intent.revision});
        }
        const pending=readPendingMaximum(resourceId,fingerprint,subjectId,id=>id!==auctionId);
        setRestored(pending?{auctionId:pending.auctionId,revision:pending.intent.revision}:null);
      } catch {
        // The form independently prevents admission when recovery cannot be read.
      }
    });
    return ()=>{current=false;};
  },[resourceId,sessionState,fingerprint,subjectId,recoveryScan,auctionId]);
  // SlotContext.resourceId is the listing id, as on the published manual bid slot.
  const candidate=currentListingAuction(query.data,resourceId);
  const auction=candidate&&(!auctionId||candidate.id===auctionId)&&hasAuctionFacts(candidate)?candidate:undefined;
  if(auction&&auction!==retained) setRetained(auction);
  const current=auction??retained;
  const replaced=Boolean(!auctionId&&recovering&&current&&recovering.id!==current.id);
  const context=replaced?recovering:current;
  if(!auctionId&&restored&&context?.id!==restored.auctionId) {
    return <AnswerArrival view={`buyer-auction:${resourceId}`}>
      <MaximumForm recoveryScope={resourceId} auctionId={restored.auctionId} revision={restored.revision}
        currency="USD" locale={locale} lifecycle={current?'replaced':'unavailable'} snapshot={current??undefined}
        onRecoveryChange={pending=>{if(!pending) {setRestored(null);scanRecovery(scan=>scan+1);}}}
        onRefresh={()=>{void query.refetch();}}/>
    </AnswerArrival>;
  }
  const separateRecovery=auctionId&&restored&&restored.auctionId!==auctionId
    ? <MaximumForm key={restored.auctionId} recoveryScope={resourceId} auctionId={restored.auctionId}
        revision={restored.revision} currency="USD" locale={locale} lifecycle="other-auction"
        onRecoveryChange={pending=>{if(!pending) {setRestored(null);scanRecovery(scan=>scan+1);}}}
        onRefresh={()=>{void query.refetch();}}/>
    : null;
  const formAuctionId=context?.id??selectedRecovery?.auctionId;
  const formRevision=context?.revision??selectedRecovery?.revision;
  if(formAuctionId&&formRevision!==undefined) {
    const form=<MaximumForm recoveryScope={resourceId} highValueMinor={context?.high_value_minor} snapshot={current??undefined} lifecycle={replaced?'replaced':auction&&!query.isError?auctionFormLifecycle(auction):'unavailable'} auctionId={formAuctionId} revision={formRevision} currency={context?.currency??'USD'} locale={locale}
      onRecoveryChange={pending=>{
        if(!auctionId) setRecovering(pending?context:null);
        if(!pending) {
          if(auctionId) setSelectedRecovery(null);
          else setRestored(null);
          scanRecovery(scan=>scan+1);
        }
      }}
      signInNext={`/buyer/auctions/${resourceId}${auctionId?`?auction=${encodeURIComponent(auctionId)}`:''}`} getQuote={context?(amount,signal,key)=>previewMaximum(context,amount,{subjectId:session.subjectId!,accessFingerprint:session.fingerprint!},signal,key):undefined}
      onRefresh={()=>{void query.refetch();}}/>;
    if(!auctionId) return <AnswerArrival view={`buyer-auction:${resourceId}`}>{form}</AnswerArrival>;
    return <><AnswerArrival view={`buyer-auction:${resourceId}:${auctionId}`}>{form}</AnswerArrival>{separateRecovery}</>;
  }
  if(!resourceId) return null;
  const message=query.isPending?t.loading:t.unavailable;
  return <><Card className="proxy-panel"><h2>{t.privateMaximum}</h2><p>{t.privacy}</p>{query.isPending?<><State title={message} body={t.privacy} kind="loading"/><RowSkeleton/></>:<State body={t.retryBody} title={message} kind={query.isError?'error':'empty'}><Button size="sm" onClick={()=>void query.refetch()}>{t.retry}</Button></State>}</Card>{separateRecovery}</>;
}

export function BuyerAuctionView({listingId,auctionId}:{locale:'en'|'ar';listingId:string;auctionId?:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  return <PageFrame>
    <PageHeader title={t.auctionBidding} lead={t.privateMaximum}
      actions={<ButtonLink size="sm" variant="ghost" href={`/${locale}/buyer`}>{t.backToBuying}</ButtonLink>}/>
    <BuyerAuctionSlot locale={locale} resourceId={listingId} auctionId={auctionId}/>
    <BuyerLanguageControl/>
  </PageFrame>;
}

const historyRead=definePageRead({
  key:(auctionId:string,revision:number,after:number)=>['auction-public-history',auctionId,revision,after],
  fresh:1000,warm:'safe',
  ask:(signal,auctionId:string,_revision:number,after:number)=>request<BidHistory>(
    `/api/web/v1/auction/v1/auctions/${encodeURIComponent(auctionId)}/history?limit=50&after_sequence=${after}`,{signal}),
});

export function PublicAuctionFacts({auction,locale}:{auction:AuctionSnapshot;locale:'en'|'ar'}) {
  const t=locale==='ar'?ar:en;
  const [cursor,setCursor]=useState<{sequence:number;amount:number}|null>(null);
  const after=cursor?.sequence??0;
  const history=usePageRead(historyRead(auction.id,auction.revision,after));
  const remaining=auctionTiming(auction.starts_at,auction.ends_at,auction.server_time)?.seconds;
  const page=history.data;
  const minimum=verifiedMinimum(auction);
  const finalBid=Array.isArray(page?.items)?page.items.at(-1):undefined;
  // Private raises can leave sequence gaps, and historical automatic responses can tie.
  const rows=page?.snapshot?.id===auction.id&&page.snapshot.revision===auction.revision&&
    Number.isSafeInteger(auction.accepted_sequence)&&auction.accepted_sequence>=0&&
    page.snapshot.accepted_sequence===auction.accepted_sequence&&
    page.snapshot.current_minor===auction.current_minor&&page.snapshot.leader===auction.leader&&
    Array.isArray(page.items)&&page.items.length<=50&&
    page.items.every((row,index)=>{
      const previous=index===0?(cursor?.amount??0):page.items[index-1].amount_minor;
      return row&&Number.isSafeInteger(row.sequence)&&
        row.sequence>(index===0?after:page.items[index-1].sequence)&&
        row.sequence<=auction.accepted_sequence&&
        isMaskedBidder(row.bidder)&&Number.isSafeInteger(row.amount_minor)&&
        row.amount_minor>0&&
        (row.amount_minor>previous||(row.amount_minor===previous&&row.automatic===true))&&
        row.amount_minor<=auction.current_minor&&row.amount_minor<=MAX_AUCTION_MINOR;
    })&&
    typeof page.has_more==='boolean'&&page.next_sequence===(page.items.at(-1)?.sequence??after)&&
    (page.has_more
      ? finalBid&&page.next_sequence<auction.accepted_sequence
      : finalBid
        ? finalBid.amount_minor===auction.current_minor&&finalBid.bidder===auction.leader
        : after===0&&auction.accepted_sequence===0)?page:undefined;
  return <section aria-label={t.auctionBidding}>
    <p>{t[auction.status]}</p>
    <dl><div><dt>{auction.accepted_sequence===0?t.openingPrice:t.currentPrice}</dt><dd><bdi>{formatMinor(auction.accepted_sequence===0?auction.opening_minor:auction.current_minor,'USD',locale)}</bdi></dd></div>
      <div><dt>{t.nextMinimum}</dt><dd><bdi>{minimum===null?t.unavailable:minimum<=MAX_AUCTION_MINOR?formatMinor(minimum,'USD',locale):t.noNextMinimum}</bdi></dd></div>
      <div><dt>{t.countdown}</dt><dd>{remaining!==undefined?formatNumber(remaining,locale,{style:'unit',unit:'second',unitDisplay:'long'}):t.missingDate}</dd></div></dl>
    <h3>{t.history}</h3>
    {history.isPending?<State kind="loading" title={t.loading} body={t.history}/>:
      history.isError||!rows?<State kind="error" title={t.historyUnavailable} body={t.retryBody}><Button onClick={()=>void history.refetch()}>{t.retry}</Button>{after>0&&<Button variant="outline" onClick={()=>setCursor(null)}>{t.firstPage}</Button>}</State>:
      <><ol>{rows.items.map(row=><li key={row.sequence}>{t.maskedBidder} <bdi>{row.bidder.replace(/^Bidder /,'')}</bdi> · <bdi>{formatMinor(row.amount_minor,'USD',locale)}</bdi></li>)}</ol>
        {auction.accepted_sequence===0&&<p>{t.noBids}</p>}
        {after>0&&<Button variant="outline" onClick={()=>setCursor(null)}>{t.firstPage}</Button>}
        {rows.has_more&&finalBid&&<Button onClick={()=>setCursor({sequence:rows.next_sequence,amount:finalBid.amount_minor})}>{t.moreHistory}</Button>}</>}
  </section>;
}
