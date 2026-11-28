'use client';
import {useEffect,useState} from 'react';
import {usePageRead} from '@/lib/page-speed/read';
import {AnswerArrival} from '@/lib/page-speed/arrival';
import {RefreshCw} from 'lucide-react';
import {formatNumber,AnimatedList,Button,ButtonLink,Card,Segmented,State,RowSkeleton,StatusBadge} from '@beirut-time/ui/foundation';
import type {ActivityView} from '@contracts/contracts-comms/buyer-workspace';
import {ApiError} from '@/lib/api/client';
import {PageHeader,PageFrame} from '@/shell/foundation/page';
import {useLocale} from '@/shell/locale-context';
import {refreshSession,signInHref,useBuyerSession} from './session';
import {activityPageBoundary,activityRead,continuesActivity,type ActivityPageBoundary} from './activity-read';
import {formatMinor} from './money';
import {buyerDateFormatter} from './buyer-date';
import {BuyerActions} from './buyer-actions';
import {BuyerReservations} from './buyer-reservations';
import {BuyerLanguageControl} from './buyer-language';
import en from './en.json';
import ar from './ar.json';

const views:ActivityView[]=['leading','outbid','won','lost','no_sale','unpaid','released','calendar'];
function auctionRecordHref(locale:string,listingId:string,auctionId:string) {
  return `/${locale}/buyer/auctions/${encodeURIComponent(listingId)}?auction=${encodeURIComponent(auctionId)}`;
}

export default function BuyerWorkspace({resultView}:{resultView?:ActivityView}={}) {
  const session=useBuyerSession();
  return <BuyerActivity key={session.fingerprint??session.state} session={session} initialView={resultView}/>;
}
function BuyerActivity({session,initialView='leading'}:{session:ReturnType<typeof useBuyerSession>;initialView?:ActivityView}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [view,setView]=useState<ActivityView>(initialView),[cursor,setCursor]=useState<string|null>(null);
  const [previous,setPrevious]=useState<ActivityPageBoundary[]>([]);
  const [restarting,setRestarting]=useState(false);
  const permitted=Boolean(session.state==='authenticated'&&session.signedIn&&session.fingerprint&&!session.organizationId&&session.roles.includes('buyer'));
  const [authorization,setAuthorization]=useState({permitted,epoch:0});
  if(authorization.permitted!==permitted) {
    setAuthorization({permitted,epoch:authorization.epoch+1});
  }
  const authorizationEpoch=authorization.epoch===0?undefined:String(authorization.epoch);
  const read=permitted&&authorization.permitted
    ?activityRead(session.fingerprint!,view,cursor,authorizationEpoch):null;
  const query=usePageRead(read);
  const {refetch}=query;
  useEffect(()=>{
    if(restarting&&cursor===null) void refetch().then(()=>setRestarting(false));
  },[restarting,cursor,refetch]);
  useEffect(()=>{if(!permitted) return;const timer=setInterval(()=>void refetch(),15000);return ()=>clearInterval(timer);},[permitted,refetch]);
  const denied=query.error instanceof ApiError&&[401,403].includes(query.error.status);
  const inconsistentPage=Boolean(query.data&&!continuesActivity(previous,query.data));
  const staleCursor=query.error instanceof ApiError&&query.error.status===409&&query.error.code==='stale_cursor';
  const auctionDenied=denied&&query.error instanceof ApiError&&query.error.code==='auction_access_denied';
  const failure=denied&&!auctionDenied?'denied':query.isError&&!staleCursor&&!auctionDenied?'unavailable':null;
  const [accessFailure,setAccessFailure]=useState<'denied'|'unavailable'|null>(null);
  // Either scoped error is issued only after current buyer verification.
  const confirmed=query.isFetchedAfterMount!==false&&!query.isFetching&&(staleCursor||auctionDenied||query.isSuccess&&query.data?.schema_version===2);
  if(failure&&failure!==accessFailure) setAccessFailure(failure);
  if(accessFailure&&!restarting&&confirmed) setAccessFailure(null);
  const [confirmedEpoch,setConfirmedEpoch]=useState<number|null>(null);
  if(confirmed&&!restarting&&authorization.epoch!==confirmedEpoch) setConfirmedEpoch(authorization.epoch);
  const verifyingAccess=authorization.epoch!==confirmedEpoch&&!(confirmed&&!restarting);
  const blocked=failure??accessFailure;
  const [activityDenied,setActivityDenied]=useState(false);
  const auctionVerified=confirmed&&query.isSuccess&&!query.isError&&query.data?.state==='available';
  if(auctionDenied&&!activityDenied) setActivityDenied(true);
  if(activityDenied&&!auctionDenied&&auctionVerified&&!restarting) setActivityDenied(false);
  const activityBlocked=auctionDenied||activityDenied;
  const canChangeView=permitted&&!blocked&&!activityBlocked&&!restarting&&!verifyingAccess;
  const data=permitted&&!blocked&&!activityBlocked&&!query.isError&&!restarting&&!verifyingAccess&&!inconsistentPage?query.data:undefined;
  const dates=buyerDateFormatter(locale);
  const date=(instant:string)=>Number.isFinite(Date.parse(instant))?dates.format(new Date(instant)):t.missingDate;
  const showAuctionHelp=data?.items.some(item=>'next_action' in item&&item.next_action==='contact_support');
  const next=data?.next_cursor??null;
  function restartPaging() {
    setRestarting(true);
    setCursor(null);
    setPrevious([]);
  }
  return <PageFrame>
    <PageHeader title={t.workspace} count={data?.state==='available'&&data.total!==null?formatNumber(data.total,locale):t.intro}
      actions={permitted?<Button busy={query.isFetching} onClick={()=>void query.refetch()}><RefreshCw aria-hidden="true"/>{t.retry}</Button>:undefined}/>
    <BuyerLanguageControl/>
    <Segmented label={t.activityView} value={view} locale={locale} options={views.map(value=>({value,label:t[value]}))}
      disabled={!canChangeView} onValueChange={value=>{if(!canChangeView) return;setView(value as ActivityView);setCursor(null);setPrevious([]);}}/>
    {session.state==='restoring'?<Card><State title={t.loading} body={t.signInBody} kind="loading"/><RowSkeleton/></Card>:
      session.state==='unavailable'?<State title={t.unavailable} body={t.retryBody} kind="error"><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></State>:
      permitted&&restarting?<Card><State title={t.loading} body={t.restartActivity} kind="loading"/><RowSkeleton/></Card>:
      permitted&&(staleCursor||inconsistentPage)?<State title={t.activityChanged} body={t.restartActivity} kind="error">
        <Button onClick={restartPaging}>{t.firstPage}</Button>
      </State>:blocked==='unavailable'?<State title={t.unavailable} body={t.retryBody} kind="error">
        <Button onClick={()=>void query.refetch()}>{t.retry}</Button>
        <Button variant="outline" onClick={restartPaging}>{t.firstPage}</Button>
      </State>:!permitted||blocked?<State title={session.signedIn?t.accessDenied:t.signIn} body={t.signInBody}>{!session.signedIn&&<ButtonLink href={signInHref('/buyer',locale)}>{t.account}</ButtonLink>}</State>:
      activityBlocked?<State title={auctionDenied?t.accessDenied:t.unavailable} body={t.retryBody}>
        <Button busy={query.isFetching} onClick={()=>void query.refetch()}>{t.retry}</Button>
        {cursor!==null&&<Button variant="outline" onClick={restartPaging}>{t.firstPage}</Button>}
      </State>:
      (verifyingAccess||query.isPending)?<Card><State title={t.loading} body={t.intro} kind="loading"/><RowSkeleton/></Card>:
      query.isError||data?.state==='unavailable'?<State title={t.unavailable} body={t.retryBody} kind="error"><Button onClick={()=>void query.refetch()}>{t.retry}</Button><Button variant="outline" onClick={restartPaging}>{t.firstPage}</Button></State>:
      data?<AnswerArrival key={view} view={`buyer-activity:${view}`}>
        <Card><AnimatedList<(typeof data.items)[number]> scopeKey={`${session.fingerprint}:${view}:${cursor}`} className="buyer-activity" items={data.items} getKey={item=>item.auction_id}
          empty={<State title={t.emptyActivity} body={t.browseBody}><ButtonLink href={`/${locale}/watches`}>{t.browse}</ButtonLink></State>}>
          {item=><article className="buyer-activity-row">
            <StatusBadge tone={'state' in item&&item.completed_sale?'success':'neutral'}>{t['state' in item?item.state:view==='calendar'?item.lifecycle:item.status??item.lifecycle]}</StatusBadge>
            {item.is_demo&&<StatusBadge>{t.demo}</StatusBadge>}
            {'listing_title' in item&&item.listing_title&&<p className="buyer-reference"><bdi>{item.listing_title}</bdi></p>}
            <p className="buyer-reference"><bdi>{item.auction_id}</bdi></p>
            <dl><div><dt>{'state' in item?t.finalPrice:item.current_price_minor===0?t.auctionBidding:t.currentPrice}</dt><dd><bdi>{'current_price_minor' in item?item.current_price_minor===0?t.noBids:formatMinor(item.current_price_minor,'USD',locale):item.final_minor===null?t.unknownTotal:formatMinor(item.final_minor,'USD',locale)}</bdi></dd></div>
              <div><dt>{'ends_at' in item?t.ends:t.ended}</dt><dd>{date('ends_at' in item?item.ends_at:item.ended_at)}</dd></div>
              {'starts_at' in item&&item.starts_at&&<div><dt>{t.starts}</dt><dd>{date(item.starts_at)}</dd></div>}</dl>
            <div className="proxy-actions">
              {'state' in item&&item.next_action==='contact_support'&&
                <ButtonLink href={`/${locale}/buyer/auctions/${encodeURIComponent(item.listing_id)}/support?auction=${encodeURIComponent(item.auction_id)}`}>{t.contactSupport}</ButtonLink>}
              {'state' in item&&item.state==='won'&&item.order_id&&item.next_action!=='contact_support'&&
                <ButtonLink variant="outline" href={`/${locale}/buyer/auctions/${encodeURIComponent(item.listing_id)}/support?auction=${encodeURIComponent(item.auction_id)}&view=history`}>{t.checkSupportHistory}</ButtonLink>}
              {'next_action' in item&&item.next_action==='contact_support'&&
                <Button variant="outline" busy={query.isFetching} onClick={()=>void refetch()}>{item.financial_state==='pending'&&!item.order_id?t.checkAllocation:t.checkResult}</Button>}
              {'order_id' in item&&item.order_id
                ? <ButtonLink href={`/${locale}/checkout/${encodeURIComponent(item.order_id)}`}>{t.reviewOrder}</ButtonLink>
                : <ButtonLink href={auctionRecordHref(locale,item.listing_id,item.auction_id)}>{t.viewAuction}</ButtonLink>}
            </div>
            {'state' in item&&item.allocation_state==='denied'&&<p>{t.allocationDenied}</p>}
            {'state' in item&&item.financial_state&&<p>
              {item.financial_state==='pending'&&!item.order_id?t.allocationPending:t[`payment_${item.financial_state}`]}
            </p>}
            {'state' in item&&<p className="buyer-note">{item.completed_sale?t.completedSale:t.notCompletedSale}</p>}
          </article>}
        </AnimatedList></Card>
        <nav className="proxy-actions" aria-label={t.pagination}>
          <Button variant="outline" disabled={!previous.length||query.isFetching} onClick={()=>{setCursor(previous[previous.length-1].cursor);setPrevious(previous.slice(0,-1));}}>{t.previousPage}</Button>
          <Button variant="outline" disabled={!next||query.isFetching} onClick={()=>{if(next){setPrevious([...previous,activityPageBoundary(cursor,data)]);setCursor(next);}}}>{t.nextPage}</Button>
        </nav>
        {showAuctionHelp&&<Card>
          <section aria-labelledby="auction-help" className="buyer-activity-row">
            <h2 id="auction-help">{t.auctionHelp}</h2>
            <p>{t.auctionHelpBody}</p>
          </section>
        </Card>}
      </AnswerArrival>:null}
    {permitted&&!blocked&&!verifyingAccess&&(!query.isError||staleCursor||auctionDenied)&&<>
      <BuyerReservations fingerprint={session.fingerprint!} authorizationEpoch={authorizationEpoch}/>
      <BuyerActions fingerprint={session.fingerprint!} authorizationEpoch={authorizationEpoch}/>
    </>}
    <footer className="buyer-foot">
      <ButtonLink variant="outline" href={`/${locale}/watches`}>{t.browse}</ButtonLink>
    </footer>
  </PageFrame>;
}
