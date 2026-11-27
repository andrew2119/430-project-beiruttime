import Checkout from '@/features/buy-now/checkout';
export default async function Page({searchParams}:{searchParams:Promise<{listing_id?:string;watch?:string}>}){const params=await searchParams;return <Checkout listingId={params.listing_id} watchId={params.watch}/>;}
