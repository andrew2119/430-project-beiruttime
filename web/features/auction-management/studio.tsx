'use client';
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, BidiReference, Card, Input } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState, refreshSession, authenticatedRequest, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { readNonSecretDraft, saveNonSecretDraft } from '@/shell/private-state';
import { auctionBase, Auction, command, displayMinor, errorCopy, incrementBands, minor, Outcome } from './api';
import en from './en.json';
import ar from './ar.json';
import { useOperationScope } from './operation-scope';
import type { SellerAuctionSnapshot } from '@contracts/contracts-auction/core';

type Draft = {listing:string;opening:string;step:string;bands:{from:string;step:string}[];starts:string;ends:string;currency:'USD'|'LBP'};
const empty:Draft={listing:'',opening:'',step:'',bands:[],starts:'',ends:'',currency:'USD'};
export default function AuctionStudio() {
  const locale=useLocale(); const session=useSession(); const sessionState=useSessionState();
  return <StudioScope key={session?.access_fingerprint??'signed-out'} session={session} locale={locale} sessionState={sessionState}/>;
}
function StudioScope({session,locale,sessionState}:{session:ReturnType<typeof useSession>;locale:'en'|'ar';sessionState:ReturnType<typeof useSessionState>}) {
  const t=locale==='ar'?ar:en; const owner=session?.access_fingerprint;
  const permitted=session?.principal.organization_grants.filter(grant=>grant.permissions.includes('identity.listings.publish'))??[];
  const [choice,setChoice]=useState(()=>owner?readNonSecretDraft(owner,'auction-organization')??session?.principal.actor.organization_id??'':'');
  const organization=permitted.some(grant=>grant.organization_id===choice)?choice:'';
  const control=permitted.length?<label className="auction-organization">{t.organization}<select dir="ltr" value={organization} onChange={event=>{
    const next=event.target.value; setChoice(next);
    if(owner) { try { saveNonSecretDraft(owner,'auction-organization',next); } catch { /* Optional convenience only. */ } }
  }}><option value="">{t.individual}</option>{permitted.map(grant=><option key={grant.organization_id} value={grant.organization_id}>{grant.organization_id}</option>)}</select></label>:null;
  return <AuctionStudioView key={organization||'individual'} session={session} locale={locale} organization={organization} organizationControl={control} sessionState={sessionState}/>;
}
function AuctionStudioView({session,locale,organization,organizationControl,sessionState}:{session:ReturnType<typeof useSession>;locale:'en'|'ar';organization:string;organizationControl:React.ReactNode;sessionState:ReturnType<typeof useSessionState>}) {
  const t=locale==='ar'?ar:en; const cache=useQueryClient(); const operationScope=useOperationScope();
  const canManage=!!session&&(organization?session.principal.organization_grants.some(grant=>grant.organization_id===organization&&grant.permissions.includes('identity.listings.publish')):session.principal.permissions.includes('identity.listings.publish'));
  const owner=session?.access_fingerprint; const scopeQuery=organization?`?organization_id=${encodeURIComponent(organization)}`:'';
  const draftKey=`auction-schedule:${organization||'individual'}`;
  const [draft,setDraft]=useState<Draft>(()=>{
    const saved=owner?readNonSecretDraft(owner,draftKey):null;
    try { return saved?{...empty,...JSON.parse(saved)}:empty; } catch { return empty; }
  }); const [reserve,setReserve]=useState('');
  const [message,setMessage]=useState(''); const [pending,setPending]=useState(false); const [uncertain,setUncertain]=useState(false); const [outcome,setOutcome]=useState<Outcome|null>(null);
  const attempt=useRef<{key:string;body:unknown}|null>(null);
  const lots=useQuery({queryKey:['auction-studio',owner,organization],enabled:!!owner&&canManage,queryFn:({signal})=>authenticatedRequest<{items:SellerAuctionSnapshot[]}>(`${auctionBase}/seller/auctions${scopeQuery}`,{signal,accessFingerprint:owner}),retry:false});
  function update<K extends keyof Draft>(key:K,value:Draft[K]) {
    const next={...draft,[key]:value}; setDraft(next); attempt.current=null;
    if(owner) { try { saveNonSecretDraft(owner,draftKey,JSON.stringify(next)); } catch { /* Optional convenience only. */ } }
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault(); if(pending||!owner||!canManage) return;
    const scope=operationScope(); setPending(true); setMessage(t.pending);
    try {
      if(!attempt.current) {
        const starts=new Date(`${draft.starts}:00Z`); const ends=new Date(`${draft.ends}:00Z`);
        if(!Number.isFinite(starts.getTime())||ends<=starts) throw new Error('invalid');
        attempt.current={key:crypto.randomUUID(),body:{listing_id:draft.listing,currency:draft.currency,opening_minor:minor(draft.opening),increment_bands:incrementBands(draft.step,draft.bands),reserve_minor:reserve?minor(reserve):null,starts_at:starts.toISOString(),ends_at:ends.toISOString()}};
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
  return <div className="auction-feature auction-studio" data-session-state={sessionState}><header className="auction-heading"><span className="eyebrow">{t.eyebrow}</span><h1>{t.title}</h1><p>{t.subtitle}</p></header>{organizationControl}
    {!session?sessionState==='restoring'?<Card><p role="status">{t.restoringSession}</p></Card>:sessionState==='unavailable'?<Card><p role="alert">{t.unavailable}</p><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></Card>:<Card><p>{t.signedout}</p><a className="button" href={signInHref('/seller/auctions',locale)}>{t.signin}</a></Card>:!canManage?<Card><p>{t.denied}</p><a className="button" href={`/${locale}/seller/verification`}>{t.applySeller}</a></Card>:<div className="auction-studio-grid">
      <Card><h2>{t.schedule}</h2><p className="muted">{t.createHelp}</p><form className="auction-form" onSubmit={submit}><fieldset className="auction-fields" disabled={pending||uncertain}>
        <label className="auction-span">{t.listing}<Input required value={draft.listing} onChange={e=>update('listing',e.target.value)} autoComplete="off" dir="ltr" pattern="[a-fA-F0-9-]{36}" /></label>
        <label>{t.currency}<select value={draft.currency} onChange={e=>update('currency',e.target.value as Draft['currency'])}><option>USD</option><option>LBP</option></select></label>
        <label>{t.opening}<Input required inputMode="decimal" value={draft.opening} onChange={e=>update('opening',e.target.value)} /></label>
        <label>{t.step}<Input required inputMode="decimal" value={draft.step} onChange={e=>update('step',e.target.value)} /></label>
        {draft.bands.map((band,index)=><fieldset className="auction-span auction-fields" key={index}><legend>{t.band} {index+2}</legend><label>{t.bandFrom}<Input required inputMode="decimal" value={band.from} onChange={event=>update('bands',draft.bands.map((value,i)=>i===index?{...value,from:event.target.value}:value))}/></label><label>{t.step}<Input required inputMode="decimal" value={band.step} onChange={event=>update('bands',draft.bands.map((value,i)=>i===index?{...value,step:event.target.value}:value))}/></label><Button type="button" className="button-secondary" onClick={()=>update('bands',draft.bands.filter((_,i)=>i!==index))}>{t.removeBand} {index+2}</Button></fieldset>)}
        <div className="auction-span"><Button type="button" className="button-secondary" disabled={draft.bands.length>=19} onClick={()=>update('bands',[...draft.bands,{from:'',step:''}])}>{t.addBand}</Button></div>
        <label>{t.reserve}<Input inputMode="decimal" value={reserve} autoComplete="off" onChange={e=>{setReserve(e.target.value);attempt.current=null;}} /></label>
        <label>{t.starts}<Input required type="datetime-local" value={draft.starts} onChange={e=>update('starts',e.target.value)} dir="ltr" /></label>
        <label>{t.ends}<Input required type="datetime-local" value={draft.ends} onChange={e=>update('ends',e.target.value)} dir="ltr" /></label>
        </fieldset><div className="auction-span auction-submit"><Button disabled={pending}>{pending?t.pending:uncertain?t.retry:t.open}</Button></div>
      </form><p role="status" aria-live="polite">{message}</p>{outcome&&<p>{t.auctionId}: <BidiReference>{outcome.auction_id}</BidiReference></p>}</Card>
      <section className="auction-list" aria-busy={lots.isFetching}>
        {lots.isError?<Card><p role="alert">{errorCopy(lots.error,t)}</p><Button onClick={()=>lots.refetch()}>{t.retry}</Button></Card>:lots.isPending?<Card><p role="status">{t.pending}</p></Card>:!lots.data?.items.length?<Card><h2>{t.empty}</h2><p>{t.emptyBody}</p></Card>:lots.data.items.map(lot=><AuctionSummary key={lot.id} lot={lot} locale={locale}/>)}
      </section></div>}
  </div>;
}
export function AuctionSummary({lot,locale}:{lot:Auction&{reserve_minor?:number|null};locale:'en'|'ar'}) {
  const t=locale==='ar'?ar:en;
  return <Card className="auction-summary"><div className="auction-row"><span className={`auction-state ${lot.status}`}>{t[lot.status]}</span><BidiReference>{lot.rules_version}</BidiReference></div>
    <h2><a href={`/${locale}/watches/${lot.listing_id}`}>{displayMinor(lot.current_minor||lot.opening_minor,lot.currency,locale)}</a></h2>
    <dl><div><dt>{t.next}</dt><dd>{displayMinor(lot.next_minimum_minor,lot.currency,locale)}</dd></div><div><dt>{t.starts}</dt><dd><BidiReference>{lot.starts_at}</BidiReference></dd></div><div><dt>{t.ends}</dt><dd><BidiReference>{lot.ends_at}</BidiReference></dd></div><div><dt>{t.server}</dt><dd><BidiReference>{lot.server_time}</BidiReference></dd></div></dl>
    <p className="muted">{lot.reserve_minor?`${t.reserveSet}: ${displayMinor(lot.reserve_minor,lot.currency,locale)}`:lot.reserve_set?t.reserveSet:t.reserveNone} · {t.extension}</p><ul>{lot.increment_bands.map(b=><li key={b.from_minor}>{displayMinor(b.from_minor,lot.currency,locale)} + {displayMinor(b.step_minor,lot.currency,locale)}</li>)}</ul>
  </Card>;
}
