'use client';
import { useQuery } from '@tanstack/react-query';
import { Gavel, LockKeyhole, RefreshCw, ShoppingBag } from 'lucide-react';
import { AnimatedList, Button, ButtonLink, BidiReference, Card, StatusBadge } from '@beirut-time/ui';
import type { BuyerWorkspace as Workspace } from '@contracts/contracts-comms/buyer-workspace';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { CardHead, LoadingRows, SectionState } from '@beirut-time/ui';
import { authenticatedRequest,refreshSession,signInHref,useBuyerSession } from './session';
import { formatMinor } from './money';
import en from './en.json';
import ar from './ar.json';

export default function BuyerWorkspace() {
  const locale=useLocale(), t=locale==='ar'?ar:en;
  const session=useBuyerSession();
  const permitted=Boolean(session.state==='authenticated'&&session.signedIn&&session.fingerprint&&!session.organizationId&&session.roles.includes('buyer'));
  const query=useQuery({queryKey:['L06','buyer-workspace',session.fingerprint], enabled:permitted,
    queryFn:({signal})=>authenticatedRequest<Workspace>('/api/web/v1/communications/v1/buyer-workspace',{signal,accessFingerprint:session.fingerprint!}),refetchInterval:15000});
  const date=(instant:string)=>new Intl.DateTimeFormat(locale==='ar'?'ar-LB':'en-LB',{
    dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(instant));
  // Read only the current access partition; no prior-owner placeholderData.
  const data=permitted?query.data:undefined;
  return <PageLayout className="buyer-workspace">
    <PageHeader title={t.workspace} count={t.intro} tag={<span className="hx-tag">{t.eyebrow}</span>}
      actions={permitted?[{id:'refresh',label:t.retry,icon:RefreshCw,busy:query.isFetching,onSelect:()=>void query.refetch()}]:undefined}/>
    {session.state==='restoring'?<Card><LoadingRows label={t.loading}/></Card>:session.state==='unavailable'?<Card><SectionState title={t.unavailable} kind="error"><Button chonk size="sm" onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></SectionState></Card>:!permitted?<Card><SectionState title={session.signedIn?t.accessDenied:t.signIn} body={t.signInBody} kind="locked" icon={LockKeyhole}>{!session.signedIn&&<ButtonLink href={signInHref('/buyer',locale)}>{t.account}</ButtonLink>}</SectionState></Card>:
      query.isPending?<Card><LoadingRows label={t.loading}/></Card>:
      query.isError?<Card><SectionState title={t.unavailable} kind="error"><Button chonk size="sm" onClick={()=>void query.refetch()}>{t.retry}</Button></SectionState></Card>:
      data?<div className="buyer-columns">
        <Card aria-label={t.activeBids}><CardHead title={t.activeBids} icon={Gavel} count={data.bids.state==='available'?data.bids.items.length:undefined}/>
          {data.bids.state==='unavailable'?<SectionState title={t.unavailable} kind="error"/>:
            <AnimatedList className="buyer-activity" items={data.bids.items} getKey={bid=>bid.auction_id} empty={<SectionState title={t.emptyBids} icon={Gavel}/>}>
              {bid=><article className="buyer-activity-row">
                <div className="buyer-item-head"><StatusBadge hue={bid.status==='leading'?'green':bid.status==='outbid'?'orange':'neutral'}>{t[bid.status]}</StatusBadge>{bid.is_demo&&<StatusBadge hue="neutral">{t.demo}</StatusBadge>}</div>
                <p className="buyer-reference"><BidiReference>{bid.auction_id}</BidiReference></p>
                <dl><div><dt>{t.currentPrice}</dt><dd><BidiReference>{formatMinor(bid.current_price_minor,bid.currency,locale)}</BidiReference></dd></div>
                  <div><dt>{t.ends}</dt><dd><time dateTime={bid.ends_at}>{date(bid.ends_at)}</time></dd></div></dl>
                <div className="proxy-actions"><ButtonLink size="sm" variant="outline" href={`/${locale}/watches/${encodeURIComponent(bid.listing_id)}`}>{t.viewAuction}</ButtonLink>
                  <ButtonLink size="sm" variant="outline" href={`/${locale}/buyer/auctions/${encodeURIComponent(bid.listing_id)}`}>{t.privateMaximum}</ButtonLink></div>
              </article>}
            </AnimatedList>}
          {data.bids.next_cursor&&<p className="buyer-note">{t.more}</p>}
        </Card>
        <Card aria-label={t.reservations}><CardHead title={t.reservations} icon={ShoppingBag} count={data.reservations.state==='available'?data.reservations.items.length:undefined}/>
          {data.reservations.state==='unavailable'?<SectionState title={t.unavailable} kind="error"/>:
            <AnimatedList className="buyer-activity" items={data.reservations.items} getKey={reservation=>reservation.reservation_id} empty={<SectionState title={t.emptyReservations} icon={ShoppingBag}/>}>
              {reservation=><article className="buyer-activity-row">
                <div className="buyer-item-head"><StatusBadge hue="orange">{t[reservation.state]}</StatusBadge>{reservation.is_demo&&<StatusBadge hue="neutral">{t.demo}</StatusBadge>}</div>
                <p className="buyer-reference"><BidiReference>{reservation.reservation_id}</BidiReference></p>
                <p>{reservation.total_minor===null?t.unknownTotal:<BidiReference>{formatMinor(reservation.total_minor,reservation.currency,locale)}</BidiReference>}</p>
                <p className="buyer-note">{reservation.expires_at?<>{t.expires} <time dateTime={reservation.expires_at}>{date(reservation.expires_at)}</time></>:t.unknownExpiry}</p>
                <ButtonLink size="sm" variant="outline" href={`/${locale}/checkout/${encodeURIComponent(reservation.reservation_id)}`}>{t.reviewReservation}</ButtonLink>
                <p className="buyer-note">{t.paymentUnavailable}</p>
              </article>}
            </AnimatedList>}
          {data.reservations.next_cursor&&<p className="buyer-note">{t.more}</p>}
          <p className="buyer-note">{t.pendingNotice}</p>
          <ButtonLink size="sm" variant="outline" href={`/${locale}/checkout`}>{t.reviewRequests}</ButtonLink>
        </Card>
      </div>:null}
    <footer className="buyer-foot"><p>{t.resultsUnavailable}</p><ButtonLink size="sm" variant="outline" href={`/${locale}/watches`}>{t.browse}</ButtonLink></footer>
  </PageLayout>;
}
