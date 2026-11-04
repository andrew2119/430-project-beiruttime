import BuyingPage from '@/features/pricing/buying';
export default async function Page({searchParams}:{searchParams:Promise<{reservation_id?:string;quote_id?:string}>}) {const query=await searchParams;return <BuyingPage reservationId={query.reservation_id} quoteId={query.quote_id}/>;}
