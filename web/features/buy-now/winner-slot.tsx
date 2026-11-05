'use client';
import {useQuery} from '@tanstack/react-query';
import {Button,ButtonLink,Card,LoadingRows,SectionState} from '@beirut-time/ui';
import {request} from '@/lib/api/client';
import {authenticatedRequest,useSession} from '@/features/identity/session';
import type {SlotContext} from '@/registry-types';

export default function WinnerSlot({resourceId,locale}:SlotContext){
  const session=useSession(),ar=locale==='ar';
  const auction=useQuery({queryKey:['l13-close-lot',resourceId],queryFn:({signal})=>request<{items:{id:string}[]}>('/api/web/v1/auction/v1/auctions?listing_id='+encodeURIComponent(resourceId!),{signal}),enabled:!!resourceId,retry:false,refetchInterval:10000});
  const id=auction.data?.items[0]?.id;
  const result=useQuery({queryKey:['l13-close',id],queryFn:({signal})=>request<{status:string}>('/api/web/v1/auction/v1/auctions/'+id+'/result',{signal}),enabled:!!id,retry:false,refetchInterval:10000});
  const mine=useQuery({queryKey:['l13-own-close',session?.access_fingerprint,id,result.data?.status],queryFn:({signal})=>authenticatedRequest<{won:boolean;order_id:string|null}>('/api/web/v1/auction/v1/auctions/'+id+'/my-result',{signal,accessFingerprint:session!.access_fingerprint}),enabled:!!id&&!!session&&session.principal.roles.includes('buyer')&&!session.principal.actor.organization_id,retry:false});
  if(!id&&!auction.error)return null;
  return <Card className="checkout-slot"><h3>{ar?'نتيجة المزاد':'Auction result'}</h3>{result.isFetching&&!result.data?<LoadingRows label={ar?'جارٍ التحقق…':'Checking current state…'}/>:result.error||auction.error?<SectionState title={ar?'النتيجة غير متاحة':'Result unavailable'} kind="error"><Button onClick={()=>{void auction.refetch();if(id)void result.refetch();}}>{ar?'أعد التحميل':'Reload'}</Button></SectionState>:<p>{result.data?.status==='no_sale'?(ar?'لا بيع — لا فائز ولا طلب':'No sale — no winner or order'):result.data?.status==='allocation_pending'?(ar?'حُسم المزاد؛ تخصيص الطلب قيد المطابقة':'Auction decided; order allocation is reconciling'):result.data?.status==='closed'?(ar?'أُغلق المزاد':'Auction closed'):result.data?.status==='allocation_denied'?(ar?'النتيجة محفوظة وتحتاج إلى مراجعة الالتزام':'Result retained; commitment review needed'):(ar?'لم يُغلق المزاد بعد':'Auction not closed yet')}</p>}{mine.error&&<SectionState title={ar?'نتيجتك الخاصة غير متاحة':'Your private result is unavailable'} kind="error"><Button onClick={()=>void mine.refetch()}>{ar?'أعد التحميل':'Reload'}</Button></SectionState>}{mine.data?.won&&mine.data.order_id&&<ButtonLink href={`/${locale}/checkout/${mine.data.order_id}`}>{ar?'تابع إلى الدفع التجريبي':'Continue to simulated payment'}</ButtonLink>}</Card>;
}
