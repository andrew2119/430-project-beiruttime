'use client';
import { useEffect, useRef, useState } from 'react';
import { BidiReference } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import type { AuctionSnapshot } from '@contracts/contracts-catalog/discovery';
import { discoveryApi } from '../discovery/api';
import { exactMoney } from '../discovery/url-state';
import en from '../discovery/en.json';
import ar from '../discovery/ar.json';
import { countdown, reconcileSnapshot, secondsRemaining, type ServerClock } from './projection';

type Connection='connecting'|'connected'|'reconnecting'|'offline'|'not_started';
export default function LiveAuction({listingId}:{listingId:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [snapshot,setSnapshot]=useState<AuctionSnapshot|null>(null),[connection,setConnection]=useState<Connection>('connecting'),[clock,setClock]=useState<ServerClock|null>(null),[now,setNow]=useState(0);
  const latest=useRef<AuctionSnapshot|null>(null);
  useEffect(()=>{
    let disposed=false, generation=0, failures=0, timer:ReturnType<typeof setTimeout>|undefined, controller:AbortController|undefined;
    latest.current=null;
    async function poll(){
      if(disposed)return;
      if(!navigator.onLine){setConnection('offline');return;}
      if(document.hidden){setConnection('reconnecting');return;}
      const mine=++generation,started=performance.now();controller=new AbortController();
      try{
        const result=await discoveryApi.auction(listingId,controller.signal);
        if(disposed||mine!==generation)return;
        if(result.state==='not_started'){latest.current=null;setSnapshot(null);setClock(null);setConnection('not_started');failures=0;}
        else if(result.state!=='available'||!result.snapshot)throw new Error('unavailable');
        else {
          const next=reconcileSnapshot(latest.current,result.snapshot);
          if(!next||next.listing_id!==listingId)throw new Error('resync');
          const receivedAt=performance.now();latest.current=next;
          setSnapshot(next);setClock({serverMs:Date.parse(next.server_time),receivedAt,roundTripMs:receivedAt-started});setNow(receivedAt);setConnection('connected');failures=0;
        }
      }catch{
        if(disposed||mine!==generation)return;
        failures++;setConnection(navigator.onLine?'reconnecting':'offline');
      }finally{
        if(!disposed&&mine===generation)timer=setTimeout(()=>void poll(),failures?Math.min(8000,1000*2**Math.min(failures-1,3)):Math.max(50,1000-(performance.now()-started)));
      }
    }
    function resume(){generation++;clearTimeout(timer);controller?.abort();if(!disposed){setConnection(navigator.onLine?'connecting':'offline');void poll();}}
    const ticker=setInterval(()=>setNow(performance.now()),1000);
    window.addEventListener('online',resume);window.addEventListener('offline',resume);document.addEventListener('visibilitychange',resume);void poll();
    return ()=>{disposed=true;generation++;clearTimeout(timer);clearInterval(ticker);controller?.abort();window.removeEventListener('online',resume);window.removeEventListener('offline',resume);document.removeEventListener('visibilitychange',resume);};
  },[listingId]);
  const fresh=connection==='connected',remaining=snapshot&&clock?secondsRemaining(snapshot.ends_at,clock,now):null;
  const status=connection==='connected'?t.liveNow:connection==='connecting'?t.connecting:connection==='offline'?t.offline:connection==='not_started'?t.notStarted:t.reconnecting;
  return <section className="live-auction" aria-labelledby="live-auction-title" data-connection={connection}>
    <div className="live-auction-heading"><h2 id="live-auction-title">{t.live}</h2><p role="status" className="discovery-help">{status}</p></div>
    {!fresh&&connection!=='not_started'&&<p className="notice">{t.auctionUnavailable}</p>}
    {snapshot&&<>
      <div className="live-auction-stats"><div><p>{t.currentPrice}{!fresh?' · —':''}</p><strong>{fresh?exactMoney(snapshot.current_price.amount,snapshot.current_price.currency,locale):'—'}</strong></div><div><p>{t.remaining}</p><strong><BidiReference>{fresh&&remaining!==null?countdown(remaining):'—'}</BidiReference></strong></div><span className="discovery-badge">{t[snapshot.status]}</span></div>
      {fresh&&<p className="discovery-help">{t.endsAt}: <time dateTime={snapshot.ends_at}>{new Intl.DateTimeFormat(locale,{timeZone:'Asia/Beirut',dateStyle:'medium',timeStyle:'short'}).format(new Date(snapshot.ends_at))}</time></p>}
      {fresh&&snapshot.status==='scheduled'&&snapshot.starts_at&&<p className="discovery-help">{t.startsAt}: <time dateTime={snapshot.starts_at}>{new Intl.DateTimeFormat(locale,{timeZone:'Asia/Beirut',dateStyle:'medium',timeStyle:'short'}).format(new Date(snapshot.starts_at))}</time></p>}
      {fresh&&remaining===0&&snapshot.status==='open'&&<p role="status">{t.elapsed}</p>}
      <p className="sr-only" role="status" key={snapshot.last_sequence}>{t.newBid} {snapshot.last_sequence}</p>
      <div className="live-auction-history"><h3>{t.history}</h3><p className="discovery-help">{t.masked}</p>{!snapshot.bids.length?<p>{t.noBids}</p>:<ol>{[...snapshot.bids].sort((a,b)=>b.sequence-a.sequence).map(bid=><li key={bid.sequence}><span><BidiReference>#{bid.sequence} · {bid.bidder_label}</BidiReference></span><strong>{exactMoney(bid.amount.amount,bid.amount.currency,locale)}</strong><time dateTime={bid.accepted_at}>{new Intl.DateTimeFormat(locale==='ar'?'ar-LB':'en-GB',{timeZone:'Asia/Beirut',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(bid.accepted_at))}</time></li>)}</ol>}{snapshot.history_truncated&&<p className="discovery-help">{t.latestHistory}</p>}</div>
      <p className="discovery-help">{t.canonicalVersion}: <BidiReference>{snapshot.revision}</BidiReference> · {t.endVersion}: <BidiReference>{snapshot.end_version}</BidiReference></p>
    </>}
  </section>;
}
