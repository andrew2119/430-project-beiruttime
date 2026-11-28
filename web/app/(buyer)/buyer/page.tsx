import {getLocale} from '@/shell/locale';
import BuyerWorkspace from '@/features/proxy-bid/buyer-workspace';
export default async function BuyerPage({searchParams}:{searchParams:Promise<{view?:string|string[]}>}) {
  const {view}=await searchParams;
  return <BuyerWorkspace resultView={view==='won'?'won':undefined} />;
}

export async function generateMetadata() {
  return {title:await getLocale()==='ar'?'مزايداتي ونتائجي · بيروت تايم':'My bids and results · Beirut Time'};
}
