import OrderDetail from '@/features/buy-now/order-detail';
export default async function Page({params}:{params:Promise<{id:string}>}){const{id}=await params;return <OrderDetail id={id}/>;}
