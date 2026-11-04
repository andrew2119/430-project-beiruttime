'use client';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Button, BidiReference, Card } from '@beirut-time/ui';
import type { BuyerWorkspace as Workspace } from '@contracts/contracts-comms/buyer-workspace';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest,refreshSession,signInHref,useBuyerSession } from './session';
import { formatMinor } from './money';
import en from './en.json';
import ar from './ar.json';

export default function BuyerWorkspace() {
  const locale=useLocale(), t=locale==='ar'?ar:en;
  const session=useBuyerSession();
  const permitted=Boolean(session.state==='authenticated'&&session.signedIn&&session.fingerprint&&session.roles.includes('buyer'));
  const query=useQuery({queryKey:['L06','buyer-workspace',session.fingerprint], enabled:permitted,
    queryFn:({signal})=>authenticatedRequest<Workspace>('/api/web/v1/communications/v1/buyer-workspace',{signal,accessFingerprint:session.fingerprint!}),refetchInterval:15000});
  const date=(instant:string)=>new Intl.DateTimeFormat(locale==='ar'?'ar-LB':'en-LB',{
    dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(instant));
  // Read only the current access partition; no prior-owner placeholderData.
  const data=permitted?query.data:undefined;
  return <div className="buyer-workspace">
    <header className="buyer-heading"><p className="eyebrow">{t.eyebrow}</p><h1>{t.workspace}</h1><p>{t.intro}</p></header>
    {session.state==='restoring'?<p role="status">{t.loading}</p>:session.state==='unavailable'?<Card><p role="status">{t.unavailable}</p><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></Card>:!permitted?<Card><h2>{session.signedIn?t.accessDenied:t.signIn}</h2><p>{t.signInBody}</p>{!session.signedIn&&<Link className="button" href={signInHref('/buyer',locale)}>{t.account}</Link>}</Card>:
      query.isPending?<p role="status">{t.loading}</p>:
      query.isError?<Card><p role="alert">{t.unavailable}</p><Button onClick={()=>void query.refetch()}>{t.retry}</Button></Card>:
      data?<div className="buyer-columns">
        <Card aria-labelledby="buyer-active-title"><h2 id="buyer-active-title">{t.activeBids}</h2>
          {data.bids.state==='unavailable'?<p role="status">{t.unavailable}</p>:
            data.bids.items.length===0?<p>{t.emptyBids}</p>:
            <ul className="buyer-activity">{data.bids.items.map(bid=><li key={bid.auction_id}>
              <div className="buyer-item-head"><span className={`buyer-status ${bid.status}`}>{t[bid.status]}</span>{bid.is_demo&&<span className="buyer-demo">{t.demo}</span>}</div>
              <BidiReference>{bid.auction_id}</BidiReference>
              <dl><div><dt>{t.currentPrice}</dt><dd><BidiReference>{formatMinor(bid.current_price_minor,bid.currency,locale)}</BidiReference></dd></div>
                <div><dt>{t.ends}</dt><dd><time dateTime={bid.ends_at}>{date(bid.ends_at)}</time></dd></div></dl>
              <div className="proxy-actions"><Link className="button button-secondary" href={`/${locale}/watches/${encodeURIComponent(bid.listing_id)}`}>{t.viewAuction}</Link>
                <Link className="button button-secondary" href={`/${locale}/buyer/auctions/${encodeURIComponent(bid.listing_id)}`}>{t.privateMaximum}</Link></div>
            </li>)}</ul>}
          {data.bids.next_cursor&&<p>{t.more}</p>}
        </Card>
        <Card aria-labelledby="buyer-reservations-title"><h2 id="buyer-reservations-title">{t.reservations}</h2>
          {data.reservations.state==='unavailable'?<p role="status">{t.unavailable}</p>:
            data.reservations.items.length===0?<p>{t.emptyReservations}</p>:
            <ul className="buyer-activity">{data.reservations.items.map(reservation=><li key={reservation.reservation_id}>
              <div className="buyer-item-head"><span className="buyer-status pending">{t[reservation.state]}</span>{reservation.is_demo&&<span className="buyer-demo">{t.demo}</span>}</div>
              <BidiReference>{reservation.reservation_id}</BidiReference>
              <p>{reservation.total_minor===null?t.unknownTotal:<BidiReference>{formatMinor(reservation.total_minor,reservation.currency,locale)}</BidiReference>}</p>
              <p>{reservation.expires_at?<>{t.expires} <time dateTime={reservation.expires_at}>{date(reservation.expires_at)}</time></>:t.unknownExpiry}</p>
              <Link className="button button-secondary" href={`/${locale}/checkout?order=${encodeURIComponent(reservation.reservation_id)}`}>{t.reviewReservation}</Link>
              <p className="buyer-note">{t.paymentUnavailable}</p>
            </li>)}</ul>}
          {data.reservations.next_cursor&&<p>{t.more}</p>}
          <p className="buyer-note">{t.pendingNotice}</p>
          <Link className="button button-secondary" href={`/${locale}/checkout`}>{t.reviewRequests}</Link>
        </Card>
      </div>:null}
    <footer className="buyer-foot"><p>{t.resultsUnavailable}</p><Link className="button button-secondary" href={`/${locale}/watches`}>{t.browse}</Link>
      {permitted&&<Button onClick={()=>void query.refetch()} disabled={query.isFetching}>{t.retry}</Button>}
    </footer>
  </div>;
}
