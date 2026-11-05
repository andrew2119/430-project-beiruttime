import OffersPage from '@/features/offers/page';
export default async function Page({searchParams}:{searchParams:Promise<Record<string,string|string[]|undefined>>}) {
 const query=await searchParams;const listing=typeof query.listing==='string'&&/^[0-9a-f-]{36}$/i.test(query.listing)?query.listing:undefined;
 return <OffersPage initialListing={listing}/>;
}
