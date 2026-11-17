'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, ButtonLink, Card, State, Skeleton } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { discoveryApi } from './api';
import { exactMoney } from './url-state';
import en from './en.json';
import ar from './ar.json';

export default function SellerView({id}:{id:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [cursor,setCursor]=useState('');
  const detail=useQuery({queryKey:['discovery','public','watch',id],queryFn:({signal})=>discoveryApi.detail(id,signal),retry:false,staleTime:0});
  const seller=detail.data?.seller;
  const listings=useQuery({queryKey:['discovery','public','seller',seller?.id,cursor],queryFn:({signal})=>discoveryApi.sellerListings(seller!.id!,cursor,signal),enabled:!!seller?.id&&!detail.isError,retry:false,staleTime:0});
  if(detail.isPending)return <section aria-label={t.seller}><Skeleton label={t.loading}/></section>;
  if(detail.isError||!seller)return <section aria-label={t.seller}><State title={t.seller} body={t.sellerUnavailable}><Button onClick={()=>void detail.refetch()}>{t.retry}</Button></State></section>;
  return <section aria-label={t.seller}><h2>{t.seller}</h2><h3>{seller.display_name}</h3>{detail.data?.demo&&<p className="notice">{t.demo}</p>}<Card className="discovery-detail-section"><p>{seller.kind==='private'?t.private:seller.kind==='dealer'?t.dealer:t.brandSeller}</p><p>{t.city}: {seller.city??t.notStated}</p><p>{seller.joined_at?`${t.joined} ${new Intl.DateTimeFormat(locale,{dateStyle:'medium'}).format(new Date(seller.joined_at))}`:t.historyUnavailable}</p><p>{seller.completed_sales==null?t.historyUnavailable:`${t.sales}: ${new Intl.NumberFormat(locale).format(seller.completed_sales)}`}</p>{seller.review_distribution&&<><h2>{t.reviews}</h2><ul>{seller.review_distribution.map((count,index)=><li key={index}>{new Intl.NumberFormat(locale).format(index+1)} / 5 · {new Intl.NumberFormat(locale).format(count)}</li>)}</ul></>}</Card><section><h2>{t.sellerListings}</h2>{!seller.id?<State title={t.sellerUnavailable} body={t.unavailableBody}/>:listings.isPending?<Skeleton label={t.loading}/>:listings.isError?<State title={t.unavailable} body={t.unavailableBody}><Button onClick={()=>void listings.refetch()}>{t.retry}</Button></State>:!listings.data?.items.length?<State title={t.empty} body={t.emptyBody}/>:<><div className="discovery-grid">{listings.data.items.map(watch=><Card key={watch.id}><ButtonLink variant="ghost" href={`/${locale}/watches/${encodeURIComponent(watch.id)}`}>{watch.title}</ButtonLink>{watch.demo&&<p className="notice">{t.demo}</p>}<p>{watch.price?exactMoney(watch.price.amount,watch.price.currency,locale):t.listingPriceUnstated}</p></Card>)}</div></>}{(cursor||(!listings.isPending&&!listings.isError&&!!listings.data?.items.length&&listings.data.next_cursor))&&<nav className="discovery-pagination" aria-label={t.results}>{cursor&&<Button onClick={()=>setCursor('')}>{t.first}</Button>}{!listings.isPending&&!listings.isError&&!!listings.data?.items.length&&listings.data.next_cursor&&<Button onClick={()=>setCursor(listings.data!.next_cursor!)}>{t.next}</Button>}</nav>}</section></section>;
}
