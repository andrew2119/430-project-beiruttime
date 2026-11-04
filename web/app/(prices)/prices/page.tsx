import PricingPage from '@/features/pricing/quotes';
export default async function Page({searchParams}:{searchParams:Promise<{quote_id?:string}>}) { const query=await searchParams; return <PricingPage initialId={query.quote_id}/>; }
