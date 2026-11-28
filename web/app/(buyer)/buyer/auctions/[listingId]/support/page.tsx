import {notFound} from 'next/navigation';
import {getLocale} from '@/shell/locale';
import {BuyerSupport} from '@/features/proxy-bid/buyer-support';

const uuid=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export async function generateMetadata() {
  return {title:await getLocale()==='ar'?'دعم المزادات · بيروت تايم':'Auction support · Beirut Time'};
}

export default async function SupportPage({params,searchParams}:{params:Promise<{listingId:string}>;searchParams:Promise<{auction?:string|string[];view?:string|string[]}>}) {
  const [{listingId},{auction,view}]=await Promise.all([params,searchParams]);
  if(!uuid.test(listingId)||typeof auction!=='string'||!uuid.test(auction)||(view!==undefined&&view!=='history')) notFound();
  return <BuyerSupport auctionId={auction.toLowerCase()} listingId={listingId.toLowerCase()} historyOnly={view==='history'}/>;
}
