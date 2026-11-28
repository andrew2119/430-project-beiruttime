import {notFound} from 'next/navigation';
import {getLocale} from '@/shell/locale';
import {BuyerAuctionView} from '@/features/proxy-bid/proxy-bid';

export default async function BuyerAuctionPage({params,searchParams}:{params:Promise<{listingId:string}>;searchParams:Promise<{auction?:string|string[]}>}) {
  const {listingId}=await params;
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(listingId)) notFound();
  const {auction}=await searchParams;
  if(auction!==undefined&&(typeof auction!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(auction))) notFound();
  const locale=await getLocale();
  return <BuyerAuctionView locale={locale} listingId={listingId.toLowerCase()} auctionId={auction?.toLowerCase()}/>;
}

export async function generateMetadata() {
  return {title:await getLocale()==='ar'?'مزايداتي ونتائجي · بيروت تايم':'My bids and results · Beirut Time'};
}
