'use client';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, RowSkeleton, State } from '@beirut-time/ui';
import type { SlotContext } from '@/registry-types';
import { useSession } from '@/features/identity/session';
import { readLots } from '@/features/auction-management/api';
import { readLegacyOperation } from './api';
import en from './en.json';
import ar from './ar.json';

type PrebidProps=SlotContext&{standalone?:boolean};
export default function PrebidSlot({resourceId,locale,standalone=false}:PrebidProps){
  const t=locale==='ar'?ar:en;const session=useSession();const owner=session?.access_fingerprint;
  const lots=useQuery({queryKey:['prebid-lots',resourceId],enabled:!!resourceId,queryFn:({signal})=>readLots(resourceId,signal),retry:false});
  const lot=lots.data?.items[0];
  const mine=useQuery({queryKey:['my-prebid',owner,lot?.id],enabled:!!lot&&!!owner&&session?.principal.roles.includes('buyer')&&!session.principal.actor.organization_id,queryFn:({signal})=>readLegacyOperation(lot!.id,owner!,signal),retry:false,refetchInterval:5000});
  if(!resourceId||!lot&&!standalone)return null;
  if(lots.isError)return <Card><State kind="error" title={t.history} body={t.unavailable}><Button onClick={()=>lots.refetch()}>{t.retry}</Button></State></Card>;
  if(lots.isPending)return <Card><RowSkeleton/><p role="status">{t.loading}</p></Card>;
  if(!lot)return null;
  const result=mine.data?.operation;
  return <Card className="auction-policy-panel"><h2>{t.title}</h2><p>{t.excluded}</p>
    {!!owner&&session?.principal.roles.includes('buyer')&&!session.principal.actor.organization_id&&(mine.isPending?<p role="status">{t.loading}</p>:mine.isError?<State kind="error" title={t.history} body={t.unavailable}><Button onClick={()=>mine.refetch()}>{t.retry}</Button></State>:result&&<div role="status"><h3>{t.history}</h3><p>{result.status==='pending'?t.pending:result.status==='denied'?t.reservation_denied:t.reserved}</p></div>)}
  </Card>;
}
