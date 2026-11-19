'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, BidiReference } from '@beirut-time/ui';
import type { SlotContext } from '@/registry-types';
import { authenticatedRequest, useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { displayMinor, errorCopy } from './api';
import en from './en.json';
import ar from './ar.json';
import type { BidNotice as Notice, OpenedBidNotice as Opened } from '@contracts/contracts-comms/bid-notices';
const base='/api/web/v1/communications/v1/bid-notices';
export default function BidNotices(props:SlotContext) {
  const session=useSession(); const sessionState=useSessionState();
  return <NoticesView key={session?.access_fingerprint??'signed-out'} {...props} session={session} sessionState={sessionState}/>;
}
function NoticesView({locale,session,sessionState}:SlotContext&{session:ReturnType<typeof useSession>;sessionState:ReturnType<typeof useSessionState>}) {
  const owner=session?.access_fingerprint;const t=locale==='ar'?ar:en;
  const [selected,setSelected]=useState<string|null>(null);
  const list=useQuery({queryKey:['bid-notices',owner],enabled:!!owner,queryFn:({signal})=>authenticatedRequest<{items:Notice[]}>(base,{signal,accessFingerprint:owner}),refetchInterval:5000,retry:false});
  const opened=useQuery({queryKey:['bid-notice-current',owner,selected],enabled:!!owner&&!!selected,queryFn:({signal})=>authenticatedRequest<Opened>(`${base}/${selected}`,{signal,accessFingerprint:owner}),retry:false});
  if(!session) return sessionState==='unavailable'?<Card className="auction-feature"><p>{t.unavailable}</p><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></Card>:null;
  return <Card className="auction-feature"><h2>{t.notices}</h2>{list.isError?<><p>{errorCopy(list.error,t)}</p><Button onClick={()=>list.refetch()}>{t.retry}</Button></>:!list.data?.items.length?<p>{t.noNotices}</p>:<ul className="auction-notices">{list.data.items.map(notice=><li key={notice.id}><div><strong>{t[notice.kind]}</strong><p>{notice.currency==='USD'?displayMinor(notice.current_minor,'USD',locale):t.legacy_currency_review} · <BidiReference>{notice.created_at}</BidiReference></p>{notice.inbox_delivery==='pending'&&<small>{t.deliveryPending}</small>}</div><Button onClick={()=>{setSelected(notice.id);if(selected===notice.id) void opened.refetch();}}>{t.viewCurrent}</Button></li>)}</ul>}
  {selected&&<div aria-live="polite"><p className="muted">{t.noticeOld}</p>{opened.isError?<p>{errorCopy(opened.error,t)}</p>:opened.data?.current?.currency==='USD'?<p>{t.current}: {displayMinor(opened.data.current.current_minor,opened.data.current.currency,locale)} · <BidiReference>{opened.data.current.ends_at}</BidiReference> <a href={`/${locale}${opened.data.notice.href}`}>{t.viewCurrent}</a></p>:<p>{opened.isFetching?t.pending:t.unavailable}</p>}</div>}
  </Card>;
}
