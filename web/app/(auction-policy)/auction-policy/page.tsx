import PolicyPage from '@/features/auction-policy/page';
export default async function Page({searchParams}:{searchParams:Promise<{listing_id?:string|string[]}>}) {
  const query=await searchParams;
  const listingId=typeof query.listing_id==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(query.listing_id)?query.listing_id:undefined;
  return <PolicyPage listingId={listingId}/>;
}
