'use client';
import { useQuery } from '@tanstack/react-query';
import { Button, ButtonLink, State } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { discoveryApi } from './api';
import { defaults, exactMoney, writeSearch } from './url-state';
import en from './en.json';
import ar from './ar.json';

export function SimilarWatches({id,brand}:{id:string;brand:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en,state={...defaults,brand};
  const query=useQuery({queryKey:['discovery','public',writeSearch(state)],queryFn:({signal})=>discoveryApi.search(state,signal),retry:false,staleTime:0});
  const items=query.data?.items.filter(item=>item.id!==id&&item.brand.toLocaleLowerCase()===brand.toLocaleLowerCase()).slice(0,3)??[];
  return <section aria-label={t.similar}><h2>{t.similar}</h2><p className="discovery-help">{t.similarBasis}</p>{query.isPending?<p role="status">{t.loading}</p>:query.isError?<State title={t.unavailable} body={t.unavailableBody}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State>:items.length?<ul>{items.map(item=><li key={item.id}><ButtonLink variant="ghost" href={`/${locale}/watches/${encodeURIComponent(item.id)}`}>{item.title} · {item.price?exactMoney(item.price.amount,item.price.currency,locale):t.listingPriceUnstated}</ButtonLink>{item.demo&&<p className="notice">{t.demo}</p>}</li>)}</ul>:<p>{t.noSimilar}</p>}<ButtonLink variant="outline" href={`/${locale}/search?${writeSearch(state)}`}>{t.allSimilar}</ButtonLink></section>;
}
