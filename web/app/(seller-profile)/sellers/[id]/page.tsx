import { getLocale } from '@/shell/locale';
import SellerProfile from '@/features/seller-profile/view';
import { sellerPage } from '@/features/seller-profile/page';
export async function generateMetadata() {
 const locale=await getLocale();
 return {title:locale==='ar'?'صفحة البائع · بيروت تايم':'Seller profile · Beirut Time'};
}
export default async function Page({params,searchParams}:{params:Promise<{id:string}>;searchParams:Promise<{page?:string|string[]}>}) {
 const {id}=await params;
 const query=await searchParams;
 return <SellerProfile key={id} id={id} initialPage={sellerPage(query.page)}/>;
}
