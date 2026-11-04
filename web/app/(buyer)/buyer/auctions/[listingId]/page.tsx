import {notFound} from 'next/navigation';
import {ButtonLink} from '@beirut-time/ui';
import {AccountLayout} from '@/shell/layouts';
import {PageLayout,PageHeader} from '@/shell/page-header';
import {getLocale} from '@/shell/locale';
import ProxyBidSlot from '@/features/proxy-bid/proxy-bid';
import en from '@/features/proxy-bid/en.json';
import ar from '@/features/proxy-bid/ar.json';
/** Workspace shortcut composes the same canonical watch slot, not another bid engine. */
export default async function BuyerAuctionPage({params}:{params:Promise<{listingId:string}>}) {
  const {listingId}=await params;
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(listingId)) notFound();
  const locale=await getLocale(),t=locale==='ar'?ar:en;
  return <AccountLayout><PageLayout className="buyer-workspace">
    <PageHeader title={t.auctionBidding} count={t.privacy} tag={<span className="hx-tag">{t.eyebrow}</span>}
      lead={<ButtonLink size="sm" variant="ghost" href={`/${locale}/buyer`}>{t.backToBuying}</ButtonLink>}/>
    <ProxyBidSlot locale={locale} resourceId={listingId}/>
  </PageLayout></AccountLayout>;
}
