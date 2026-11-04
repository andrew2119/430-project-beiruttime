import PricingPage from '@/features/pricing/quotes';
import BuyingPage from '@/features/pricing/buying';
import InboxPage from '@/features/inbox/page';
import SignIn from '../../signin';
export default async function Page({params,searchParams}:{params:Promise<{screen:string}>;searchParams:Promise<{quote_id?:string;reservation_id?:string}>}) {const {screen}=await params;const query=await searchParams;return screen==='prices'?<PricingPage initialId={query.quote_id}/>:screen==='buying'?<BuyingPage reservationId={query.reservation_id} quoteId={query.quote_id}/>:screen==='inbox'?<InboxPage/>:<SignIn/>;}
