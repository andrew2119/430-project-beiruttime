'use client';
import { useQueries } from '@tanstack/react-query';
import { Button, ButtonLink, Card, State } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { discoveryApi } from './api';
import { exactMoney } from './url-state';
import en from './en.json';
import ar from './ar.json';

export function toggleComparison(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter(value=>value!==id) : ids.length<3 ? [...ids,id] : ids;
}
export function Comparison({ids,remove}:{ids:string[];remove:(id:string)=>void}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const queries=useQueries({queries:ids.slice(0,3).map(id=>({queryKey:['discovery','public','watch',id],queryFn:({signal}:{signal:AbortSignal})=>discoveryApi.detail(id,signal),retry:false,staleTime:0,refetchInterval:15000}))});
  if(!ids.length)return null;
  return <section aria-label={t.compare}><h2>{t.compare}</h2><p className="discovery-help">{t.compareHelp}</p><div className="discovery-grid">{queries.map((query,index)=>{
    const watch=query.data,id=ids[index];
    return <Card key={id} className="discovery-detail-section">{query.isPending?<p role="status">{t.loading}</p>:query.isError||!watch||watch.sale_state!=='available'?<State title={t.listingUnavailable} body={t.listingUnavailableBody}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State>:<><h3>{watch.title}</h3>{watch.demo&&<p className="notice">{t.demo}</p>}<p>{watch.price?exactMoney(watch.price.amount,watch.price.currency,locale):t.listingPriceUnstated}</p><p>{watch.condition||t.notStated}</p><p>{watch.no_documents===true?t.noDocuments:watch.no_documents===false?t.papers:t.documentsUnknown}</p><p>{watch.seller.display_name} · {watch.location}</p><ButtonLink href={`/${locale}/watches/${encodeURIComponent(id)}`}>{t.details}</ButtonLink></>}<Button variant="outline" onClick={()=>remove(id)}>{t.removeComparison}</Button></Card>;
  })}</div></section>;
}
