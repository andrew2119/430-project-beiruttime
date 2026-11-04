'use client';
import { useQuery } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Skeleton } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { discoveryApi } from './api';
import { exactMoney, saleStateLabel } from './url-state';
import { Gallery } from './photo';
import { WatchSlots } from './watch-slots';
import LiveAuction from '../live-bids/live-auction';
import en from './en.json';
import ar from './ar.json';
export default function WatchView({id}:{id:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const query=useQuery({queryKey:['discovery','public','watch',id],queryFn:({signal})=>discoveryApi.detail(id,signal),retry:false,refetchInterval:15000,refetchOnWindowFocus:true,staleTime:0});
  if(query.isPending)return <Skeleton label={t.loading}/>;
  const watch=query.data,notFound=query.error instanceof ApiError&&query.error.status===404;
  // A failed availability refresh must not retain a purchase affordance.
  if(query.isError||!watch)return <div className="discovery-page discovery-message" role="alert"><h1>{notFound?t.listingUnavailable:t.unavailable}</h1><p>{notFound?t.listingUnavailableBody:t.unavailableBody}</p><Button onClick={()=>void query.refetch()}>{t.retry}</Button><ButtonLink className="button-secondary" href={`/${locale}/watches`}>{t.back}</ButtonLink></div>;
  const assurance=watch.assurance;
  const includedLabels:Record<string,string>={box:t.box,papers:t.papers,links:t.links};
  const assuranceTitle=assurance.kind==='official_business'?(assurance.status==='onboarded'?t.official:t.assuranceUnavailable):({pending:t.pending,passed:t.passed,failed:t.failed,inconclusive:t.inconclusive,unavailable:t.assuranceUnavailable,onboarded:t.assuranceUnavailable}[assurance.status]);
  return <div className="discovery-page">
    <ButtonLink className="button-secondary discovery-back" href={`/${locale}/watches`}><span className="direction-arrow" aria-hidden="true">←</span>{t.back}</ButtonLink>
    <div className="discovery-detail-grid"><Gallery photos={watch.photos} unavailable={watch.media_state==='unavailable'}/><div className="discovery-detail-copy">
      <p className="eyebrow">{watch.brand} · <BidiReference>{watch.model}</BidiReference></p><h1>{watch.title}</h1><p className="discovery-help">{watch.location}</p>
      <div className="discovery-sale"><span className="discovery-badge">{t[watch.sale_mode==='fixed'?'fixed':watch.sale_mode==='offer'?'offer':'auction']} · {saleStateLabel(watch.sale_state,t)}</span><p className="discovery-help">{t.listingPrice}</p><strong>{watch.price?exactMoney(watch.price.amount,watch.price.currency,locale):t.listingPriceUnstated}</strong></div>
      {watch.demo&&<p className="notice">{t.demo}</p>}
      <section className="discovery-detail-section"><h2>{t.details}</h2>{watch.description&&<p>{watch.description}</p>}<dl>{watch.reference&&<div><dt>{t.reference}</dt><dd><BidiReference>{watch.reference}</BidiReference></dd></div>}{watch.year&&<div><dt>{t.year}</dt><dd>{new Intl.NumberFormat(locale,{useGrouping:false}).format(watch.year)}</dd></div>}<div><dt>{t.condition}</dt><dd>{watch.condition||t.notStated}</dd></div>{Object.entries(watch.component_wear??{}).map(([component,wear])=><div key={component}><dt>{t[component as 'case'|'dial'|'crystal'|'bracelet'|'movement']}</dt><dd>{wear||t.notStated}</dd></div>)}<div><dt>{t.included}</dt><dd>{watch.included_items.length?watch.included_items.map(item=>(includedLabels[item]??item)).join(' · '):t.notStated}</dd></div></dl></section>
      <section className="discovery-detail-section"><h2>{t.modifications}</h2><p>{watch.modified?t.modified:t.notModified}</p>{watch.modified&&<ul>{watch.modified_parts.map((part,index)=><li key={index}>{part}</li>)}</ul>}</section>
      <section className="discovery-detail-section"><h2>{t.seller}</h2><h3>{watch.seller.display_name}</h3><p>{watch.seller.kind==='private'?t.private:watch.seller.kind==='dealer'?t.dealer:t.brandSeller}</p><p className="discovery-help">{watch.seller.completed_sales===null?t.historyUnavailable:`${t.sales}: ${new Intl.NumberFormat(locale).format(watch.seller.completed_sales)}`}</p>{watch.seller.joined_at&&<p className="discovery-help">{t.joined} {new Intl.DateTimeFormat(locale,{year:'numeric',month:'long'}).format(new Date(watch.seller.joined_at))}</p>}</section>
      <section className="discovery-assurance"><p className="eyebrow">{t.assurance}</p><h2>{assuranceTitle}</h2><p>{assurance.kind==='official_business'?(assurance.status==='onboarded'?t.officialBody:t.officialUnknownBody):t.privateBody}</p></section>
    </div></div>
    {watch.sale_mode==='auction'&&<LiveAuction key={watch.id} listingId={watch.id}/>}
    <section className="discovery-actions">{watch.sale_state==='available'?<WatchSlots key={watch.id} id={watch.id} locale={locale}/>:null}<p className="discovery-help">{t.actionsUnavailable}</p></section>
  </div>;
}
