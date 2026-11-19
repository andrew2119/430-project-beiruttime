'use client';
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatedList, Button, ButtonLink, BidiReference, Card, Input, State, StatusBadge } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { PolicyPanel } from '@/features/auction-policy/panel';
import { readPolicy } from '@/features/auction-policy/api';
import { Select, RowSkeleton } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState, refreshSession, authenticatedRequest, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { readNonSecretDraft, saveNonSecretDraft } from '@/shell/private-state';
import { auctionBase, Auction, command, displayMinor, errorCopy, incrementBands, minor, Outcome, reviewSchedule, type ScheduleReview } from './api';
import en from './en.json';
import ar from './ar.json';
import { useOperationScope } from './operation-scope';
import type { SellerAuctionSnapshot } from '@contracts/contracts-auction/core';

import {restoreDraft,type Draft} from './draft';
export default function AuctionStudio() {
  const locale=useLocale(); const session=useSession(); const sessionState=useSessionState();
  return <StudioScope key={session?.access_fingerprint??'signed-out'} session={session} locale={locale} sessionState={sessionState}/>;
}
function StudioScope({session,locale,sessionState}:{session:ReturnType<typeof useSession>;locale:'en'|'ar';sessionState:ReturnType<typeof useSessionState>}) {
  const t=locale==='ar'?ar:en; const owner=session?.access_fingerprint;
  const permitted=session?.principal.organization_grants.filter(grant=>grant.permissions.includes('identity.listings.publish'))??[];
  const [choice,setChoice]=useState(()=>owner?readNonSecretDraft(owner,'auction-organization')??session?.principal.actor.organization_id??'':'');
  const organization=permitted.some(grant=>grant.organization_id===choice)?choice:'';
  const control=permitted.length?<label className="auction-organization">{t.organization}<Select aria-label={t.organization} value={organization} onValueChange={next=>{
    setChoice(next);
    if(owner) { try { saveNonSecretDraft(owner,'auction-organization',next); } catch { /* Optional convenience only. */ } }
  }} options={[{value:'',label:t.individual},...permitted.map(grant=>({value:grant.organization_id,label:grant.organization_id}))]}/></label>:null;
  return <AuctionStudioView key={organization||'individual'} session={session} locale={locale} organization={organization} organizationControl={control} sessionState={sessionState}/>;
}
function AuctionStudioView({session,locale,organization,organizationControl,sessionState}:{session:ReturnType<typeof useSession>;locale:'en'|'ar';organization:string;organizationControl:React.ReactNode;sessionState:ReturnType<typeof useSessionState>}) {
  const t=locale==='ar'?ar:en; const cache=useQueryClient(); const operationScope=useOperationScope();
  const canManage=!!session&&(organization?session.principal.organization_grants.some(grant=>grant.organization_id===organization&&grant.permissions.includes('identity.listings.publish')):session.principal.permissions.includes('identity.listings.publish'));
  const owner=session?.access_fingerprint; const scopeQuery=organization?`?organization_id=${encodeURIComponent(organization)}`:'';
  const draftKey=`auction-schedule:${organization||'individual'}`;
  const [draft,setDraft]=useState<Draft>(()=>{
    const saved=owner?readNonSecretDraft(owner,draftKey):null;
    return restoreDraft(saved);
  }); const [reserve,setReserve]=useState('');
  const [timeReview,setTimeReview]=useState<ScheduleReview|null>(null);
  const [message,setMessage]=useState(''); const [pending,setPending]=useState(false); const [uncertain,setUncertain]=useState(false); const [outcome,setOutcome]=useState<Outcome|null>(null);
  const attempt=useRef<{key:string;body:unknown}|null>(null);
  const lots=useQuery({queryKey:['auction-studio',owner,organization],enabled:!!owner&&canManage,queryFn:({signal})=>authenticatedRequest<{items:SellerAuctionSnapshot[]}>(`${auctionBase}/seller/auctions${scopeQuery}`,{signal,accessFingerprint:owner}),retry:false});
  function update<K extends keyof Draft>(key:K,value:Draft[K]) {
    const next={...draft,[key]:value}; setDraft(next); attempt.current=null;
    if(key==='starts'||key==='ends')setTimeReview(null);
    if(owner) { try { saveNonSecretDraft(owner,draftKey,JSON.stringify(next)); } catch { /* Optional convenience only. */ } }
  }
  async function interpretTimes(){
    if(!owner||pending||uncertain)return;
    const scope=operationScope();setPending(true);setTimeReview(null);
    try{const result=await reviewSchedule(draft.starts,draft.ends,owner,scope.controller.signal);if(scope.active){setTimeReview(result);setMessage('');}}
    catch(error){if(scope.active)setMessage(errorCopy(error,t));}
    finally{if(scope.active)setPending(false);}
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault(); if(pending||!owner||!canManage) return;
    const scope=operationScope(); setPending(true); setMessage(t.pending);
    try {
      if(!attempt.current) {
        if(!timeReview||timeReview.starts.local!==draft.starts||timeReview.ends.local!==draft.ends)throw new ApiError(422,'schedule_review_required','');
        attempt.current={key:crypto.randomUUID(),body:{listing_id:draft.listing,currency:'USD',opening_minor:minor(draft.opening),increment_bands:incrementBands(draft.step,draft.bands),reserve_minor:reserve?minor(reserve):null,starts_local:draft.starts,ends_local:draft.ends,confirmed_starts_at:timeReview.starts.utc,confirmed_ends_at:timeReview.ends.utc}};
      }
      const result=await command(`/auctions${scopeQuery}`,attempt.current.body,attempt.current.key,scope.controller.signal,owner);
      if(!scope.active) return;
      setOutcome(result); setUncertain(false); setMessage(result.status==='succeeded'?t.success:(t[result.code as keyof typeof t]??t.invalid));
      attempt.current=null; void cache.invalidateQueries({queryKey:['auction-studio',owner,organization]});
    } catch(error) {
      if(scope.active) {
        const unknown=!!attempt.current&&(!(error instanceof ApiError)||error.status>=500);
        setUncertain(unknown); if(!unknown) attempt.current=null;
        setMessage(errorCopy(error,t));
      }
    }
    finally { if(scope.active) setPending(false); }
  }
  return <PageLayout className="auction-feature auction-studio"><div data-session-state={sessionState}><PageHeader title={t.title} count={t.subtitle} tools={organizationControl}/>
    {!session?sessionState==='restoring'?<State kind="loading" title={t.title} body={t.restoringSession}/>:sessionState==='unavailable'?<State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></State>:<State title={t.title} body={t.signedout}><ButtonLink href={signInHref('/seller/auctions',locale)}>{t.signin}</ButtonLink></State>:!canManage?<State title={t.title} body={t.denied}><ButtonLink href={`/${locale}/seller/verification`}>{t.applySeller}</ButtonLink></State>:<div className="auction-studio-grid">
      <Card><h2>{t.schedule}</h2><p className="muted">{t.createHelp}</p><form className="auction-form" onSubmit={submit}><fieldset className="auction-fields" disabled={pending||uncertain}>
        <label className="auction-span">{t.listing}<Input required value={draft.listing} onChange={e=>update('listing',e.target.value)} autoComplete="off" dir="ltr" pattern="[a-fA-F0-9-]{36}" /></label>
        <p>{t.currency}: USD</p>
        <label>{t.opening}<Input required inputMode="decimal" value={draft.opening} onChange={e=>update('opening',e.target.value)} /></label>
        <label>{t.step}<Input required inputMode="decimal" value={draft.step} onChange={e=>update('step',e.target.value)} /></label>
        {draft.bands.map((band,index)=><fieldset className="auction-span auction-fields" key={index}><legend>{t.band} {index+2}</legend><label>{t.bandFrom}<Input required inputMode="decimal" value={band.from} onChange={event=>update('bands',draft.bands.map((value,i)=>i===index?{...value,from:event.target.value}:value))}/></label><label>{t.step}<Input required inputMode="decimal" value={band.step} onChange={event=>update('bands',draft.bands.map((value,i)=>i===index?{...value,step:event.target.value}:value))}/></label><Button type="button" variant="outline" onClick={()=>update('bands',draft.bands.filter((_,i)=>i!==index))}>{t.removeBand} {index+2}</Button></fieldset>)}
        <div className="auction-span"><Button type="button" variant="outline" disabled={draft.bands.length>=19} onClick={()=>update('bands',[...draft.bands,{from:'',step:''}])}>{t.addBand}</Button></div>
        <label>{t.reserve}<Input inputMode="decimal" value={reserve} autoComplete="off" onChange={e=>{setReserve(e.target.value);attempt.current=null;}} /></label>
        <label>{t.starts}<Input required type="datetime-local" value={draft.starts} onChange={e=>update('starts',e.target.value)} dir="ltr" /></label>
        <label>{t.ends}<Input required type="datetime-local" value={draft.ends} onChange={e=>update('ends',e.target.value)} dir="ltr" /></label>
        <div className="auction-span"><Button type="button" variant="outline" onClick={interpretTimes} disabled={!draft.starts||!draft.ends}>{t.interpretTime}</Button>{timeReview&&<div><p>{t.confirmTime}</p><p><BidiReference>{timeReview.starts.local} ({timeReview.starts.offset})</BidiReference></p><p><BidiReference>{timeReview.ends.local} ({timeReview.ends.offset})</BidiReference></p></div>}</div>
        </fieldset><div className="auction-span auction-submit"><Button disabled={pending||(!uncertain&&!timeReview)}>{pending?t.pending:uncertain?t.retry:t.open}</Button></div>
      </form><p role="status" aria-live="polite">{message}</p>{outcome&&<p>{t.auctionId}: <BidiReference>{outcome.auction_id}</BidiReference></p>}</Card>
      <section className="auction-list" aria-busy={lots.isFetching}>
        {lots.isError?<State kind="error" title={t.title} body={errorCopy(lots.error,t)}><Button onClick={()=>lots.refetch()}>{t.retry}</Button></State>:lots.isPending?<div role="status" aria-label={t.pending}><RowSkeleton media="cover"/><span className="sr-only">{t.pending}</span></div>:!lots.data?.items.length?<State title={t.empty} body={t.emptyBody}/>:<AnimatedList items={lots.data.items} getKey={lot=>lot.id}>{lot=><div className="auction-list"><AuctionSummary lot={lot} locale={locale} organization={organization}/><PolicyPanel id={lot.id} locale={locale} editable organization={organization} currency={lot.currency}/></div>}</AnimatedList>}
      </section></div>}
  </div></PageLayout>;
}
export function AuctionSummary({lot,locale,organization=''}:{lot:Auction&{reserve_minor?:number|null};locale:'en'|'ar';organization?:string}) {
  const session=useSession();
  // Share PolicyPanel's current projection, since seller v1 intentionally has no mode field.
  const policy=useQuery({queryKey:['auction-policy',lot.id,session?.access_fingerprint,organization],queryFn:({signal})=>readPolicy(lot.id,signal),retry:false,refetchInterval:5000});
  const mode=policy.data?.mode??lot.mode;
  const t=locale==='ar'?ar:en; const held=!!mode&&mode!=='bidding';
  if(lot.currency!=='USD')return <Card><State title={t.title} body={t.legacy_currency_review}/></Card>;
  return <Card className="auction-summary"><div className="auction-row"><StatusBadge hue={held?'orange':lot.status==='live'?'green':lot.status==='scheduled'?'blue':'neutral'}>{held?t.heldStatus:t[lot.status]}</StatusBadge><BidiReference>{lot.rules_version}</BidiReference></div>
    <h2><a href={`/${locale}/watches/${lot.listing_id}`}>{displayMinor(lot.current_minor||lot.opening_minor,lot.currency,locale)}</a></h2>
    <dl><div><dt>{t.next}</dt><dd>{displayMinor(lot.next_minimum_minor,lot.currency,locale)}</dd></div><div><dt>{t.startsUtc}</dt><dd><BidiReference>{lot.starts_at}</BidiReference></dd></div><div><dt>{t.endsUtc}</dt><dd><BidiReference>{lot.ends_at}</BidiReference></dd></div><div><dt>{t.server}</dt><dd><BidiReference>{lot.server_time}</BidiReference></dd></div></dl>
    <p className="muted">{lot.reserve_minor?`${t.reserveSet}: ${displayMinor(lot.reserve_minor,lot.currency,locale)}`:lot.reserve_set?t.reserveSet:t.reserveNone}</p><ul>{lot.increment_bands.map(b=><li key={b.from_minor}>{displayMinor(b.from_minor,lot.currency,locale)} + {displayMinor(b.step_minor,lot.currency,locale)}</li>)}</ul>
  </Card>;
}
