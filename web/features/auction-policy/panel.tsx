'use client';
import { useQuery } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, RowSkeleton, State, StatusBadge } from '@beirut-time/ui';
import { useSession } from '@/features/identity/session';
import type { PolicySnapshot, SellerPolicySnapshot } from '@contracts/contracts-auction/policy';
import { readPolicy, readSellerPolicy } from './api';
import en from './en.json';
import ar from './ar.json';
export function PolicyPanel({id,locale,editable=false,organization=''}:{id:string;locale:'en'|'ar';editable?:boolean;organization?:string;currency?:string}){
  const session=useSession();const t=locale==='ar'?ar:en;
  const policy=useQuery<PolicySnapshot|SellerPolicySnapshot>({queryKey:['auction-policy',id,session?.access_fingerprint,organization,editable],enabled:!editable||!!session,queryFn:({signal})=>editable?readSellerPolicy(id,session!.access_fingerprint,signal,organization):readPolicy(id,signal),retry:false,refetchInterval:5000});
  if(editable&&!session)return <Card><p>{t.signedout}</p></Card>;
  if(policy.isPending)return <Card><RowSkeleton/><span role="status">{t.loading}</span></Card>;
  if(policy.isError)return <State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>policy.refetch()}>{t.retry}</Button></State>;
  return <Card className="auction-policy-panel"><PolicyFacts policy={policy.data} locale={locale}/>
    {editable&&'cancellation_eligible' in policy.data&&policy.data.cancellation_eligible&&<ButtonLink href={`/${locale}/seller/listings`}>{t.cancelLink}</ButtonLink>}
  </Card>;
}
export function PolicyFacts({policy,locale}:{policy:PolicySnapshot|SellerPolicySnapshot;locale:'en'|'ar';currency?:string}){const t=locale==='ar'?ar:en;return <>
  <div className="auction-policy-row"><h2>{t.title}</h2><StatusBadge hue={policy.frozen?'orange':'blue'}>{policy.frozen?t.frozen:t.fixedEnd}</StatusBadge></div>
  <p>{policy.reserve_set?t.reserve:t.noReserve}</p>
  {'reserve_met' in policy&&policy.reserve_set&&<p>{policy.reserve_met?t.reserveMet:t.reserveNotMet}</p>}
  <p>{t.fixedEnd}</p><p className="muted">{t.boundary}</p>
  <dl><div><dt>{t.ends}</dt><dd><BidiReference>{policy.current_ends_at}</BidiReference></dd></div><div><dt>{t.version}</dt><dd><BidiReference>{policy.end_version}</BidiReference></dd></div></dl>
  <p>{t.excluded}</p>{policy.schedule_state==='ended_legacy_review'?<p role="status">{t.endedReview}</p>:policy.mode!=='bidding'&&<p role="status">{t.held}</p>}
</>;}
