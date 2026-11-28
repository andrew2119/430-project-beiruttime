'use client';
import { useQuery } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, Skeleton, State, StatusBadge } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { discoveryApi } from './api';
import { exactMoney, saleStateLabel } from './url-state';
import { WatchHistory } from './history';
import { SimilarWatches } from './similar';
import SellerView from './seller-view';
import { Gallery } from './photo';
import { WatchSlots } from './watch-slots';
import LiveAuction from '../live-bids/live-auction';
import en from './en.json';
import ar from './ar.json';
export default function WatchView({id}:{id:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const query=useQuery({queryKey:['discovery','public','watch',id],queryFn:({signal})=>discoveryApi.detail(id,signal),retry:false,refetchInterval:15000,refetchOnWindowFocus:true,staleTime:0});
  if(query.isPending)return <PageLayout className="discovery-page"><Skeleton label={t.loading}/><div className="discovery-detail-grid" aria-hidden="true"><Skeleton className="aspect-square"/><Skeleton className="aspect-square"/></div></PageLayout>;
  const denied=query.error instanceof ApiError&&query.error.status===403;
  const watch=query.data,notFound=query.error instanceof ApiError&&query.error.status===404;
  // A failed availability refresh must not retain a purchase affordance.
  if(query.isError||!watch)return <PageLayout><div role="alert"><State kind="error" title={denied?t.denied:notFound?t.listingUnavailable:t.unavailable} body={denied?t.deniedBody:notFound?t.listingUnavailableBody:t.unavailableBody}><Button chonk size="sm" onClick={()=>void query.refetch()}>{t.retry}</Button><ButtonLink variant="outline" size="sm" href={`/${locale}/watches`}>{t.back}</ButtonLink></State></div></PageLayout>;
  const assurance=watch.assurance;
  const includedLabels:Record<string,string>={box:t.box,papers:t.papers,links:t.links};
  const assuranceTitle=assurance.kind==='official_business'?(assurance.status==='onboarded'?t.official:t.assuranceUnavailable):({pending:t.pending,passed:t.passed,failed:t.failed,inconclusive:t.inconclusive,unavailable:t.assuranceUnavailable,onboarded:t.assuranceUnavailable}[assurance.status]);
  return <PageLayout className="discovery-page">
    <PageHeader title={watch.title} count={<>{watch.brand} · <BidiReference>{watch.model}</BidiReference> · {watch.location}</>} lead={<ButtonLink variant="ghost" size="sm" href={`/${locale}/watches`}><span className="direction-arrow" aria-hidden="true">←</span>{t.back}</ButtonLink>} tag={<StatusBadge hue={watch.sale_mode==='auction'?'blue':'neutral'}>{t[watch.sale_mode==='fixed'?'fixed':watch.sale_mode==='offer'?'offer':'auction']} · {saleStateLabel(watch.sale_state,t)}</StatusBadge>}/>
    <div className="discovery-detail-grid"><Gallery photos={watch.photos} unavailable={watch.media_state==='unavailable'}/><div className="discovery-detail-copy">
      <Card className="discovery-sale"><p className="discovery-help">{t.listingPrice}</p><strong>{watch.price?exactMoney(watch.price.amount,watch.price.currency,locale):t.listingPriceUnstated}</strong></Card>
      {watch.demo&&<p className="notice">{t.demo}</p>}
      <Card className="discovery-detail-section"><h2>{t.details}</h2>{watch.description&&<p>{watch.description}</p>}<dl>{watch.reference&&<div><dt>{t.reference}</dt><dd><BidiReference>{watch.reference}</BidiReference></dd></div>}{watch.year&&<div><dt>{t.year}</dt><dd>{new Intl.NumberFormat(locale,{useGrouping:false}).format(watch.year)}</dd></div>}<div><dt>{t.condition}</dt><dd>{watch.condition||t.notStated}</dd></div>{Object.entries(watch.component_wear??{}).map(([component,wear])=><div key={component}><dt>{t[component as 'case'|'dial'|'crystal'|'bracelet'|'movement']}</dt><dd>{wear||t.notStated}</dd></div>)}<div><dt>{t.included}</dt><dd>{watch.included_items.length?watch.included_items.map(item=>(includedLabels[item]??item)).join(' · '):t.notStated}</dd></div></dl></Card>
      <p className="notice">{watch.no_documents===true?t.noDocuments:watch.no_documents===false?t.papers:t.documentsUnknown}</p>
      <Card className="discovery-detail-section"><h2>{t.modifications}</h2><p>{watch.modified?t.modified:t.notModified}</p>{watch.modified&&<ul>{watch.modified_parts.map((part,index)=><li key={index}>{part}</li>)}</ul>}</Card>
      <SellerView key={watch.id} id={watch.id}/>
      <Card className="discovery-detail-section"><WatchHistory key={`${watch.id}:${watch.revision}:${watch.history_revision}`} watch={watch}/>{watch.seller.review_distribution&&<><h3>{t.reviews}</h3><ul>{watch.seller.review_distribution.map((count,index)=><li key={index}>{new Intl.NumberFormat(locale).format(index+1)} / 5 · {new Intl.NumberFormat(locale).format(count)}</li>)}</ul></>}</Card>
      <Card className="discovery-detail-section"><p className="discovery-help">{t.assurance}</p><h2>{assuranceTitle}</h2><p>{assurance.kind==='official_business'?(assurance.status==='onboarded'?t.officialBody:t.officialUnknownBody):t.privateBody}</p></Card>
    </div></div>
    {watch.sale_mode==='auction'&&<LiveAuction key={watch.id} listingId={watch.id}/>}
    <SimilarWatches id={watch.id} brand={watch.brand}/>
    <section className="discovery-actions">{watch.sale_state==='available'?<WatchSlots key={watch.id} id={watch.id} locale={locale}/>:null}<p className="discovery-help">{t.actionsUnavailable}</p></section>
  </PageLayout>;
}
