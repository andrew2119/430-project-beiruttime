'use client';
import { useQuery } from '@tanstack/react-query';
import { AnimatedList, Button, ButtonLink, Card, RowSkeleton, State } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { readLots } from '@/features/auction-management/api';
import { PolicyPanel } from './panel';
import PrebidSlot from './prebid-slot';
import en from './en.json';
import ar from './ar.json';
export default function PolicyPage({listingId}:{listingId?:string}={}){const locale=useLocale();const t=locale==='ar'?ar:en;
  const lots=useQuery({queryKey:['policy-auctions'],queryFn:({signal})=>readLots(undefined,signal),retry:false});
  return <PageLayout className="auction-policy-page"><PageHeader title={t.title} count={t.description}/>
    {listingId&&<PrebidSlot resourceId={listingId} locale={locale} standalone/>}
    {lots.isPending?<Card><RowSkeleton/><p role="status">{t.loading}</p></Card>:lots.isError?<State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>lots.refetch()}>{t.retry}</Button></State>:!lots.data.items.length?<State title={t.empty} body={t.emptyBody}/>:<AnimatedList items={lots.data.items} getKey={lot=>lot.id}>{lot=><section className="auction-policy-item"><PolicyPanel id={lot.id} locale={locale} currency={lot.currency}/><div className="auction-policy-actions"><ButtonLink href={`/${locale}/watches/${lot.listing_id}`}>{t.public}</ButtonLink><ButtonLink href={`/${locale}/auction-policy?listing_id=${lot.listing_id}`}>{t.purchaseStatus}</ButtonLink></div></section>}</AnimatedList>}
  </PageLayout>;
}
