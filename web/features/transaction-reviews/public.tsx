'use client';
import './reviews.css';
import { Button, Card, State, formatNumber } from '@beirut-time/ui/foundation';
import { useLocale } from '@/shell/locale-context';
export type ReviewPage = {items:{review_ref:string;rating:number;text:string;reply:string|null}[];total:number;average:number|null;distribution:number[];page:number;next_page:number|null};
export function PublicReviews({data,onPage,onReport}:{data:ReviewPage;onPage:(page:number)=>void;onReport:(reference:string)=>void}) {
  const locale=useLocale(); const ar=locale==='ar';
  return <section className="transaction-reviews-content" aria-label={ar?'تقييمات المشترين':'Buyer ratings'}>
    <p>{ar?'عدد المراجعات':'Review count'}: {formatNumber(data.total,locale)}</p>
    <p>{ar?'المتوسط':'Average'}: {formatNumber(data.average,locale,{maximumFractionDigits:2})}</p>
    <ol>{data.distribution.map((count,index)=><li key={index}>{formatNumber(index+1,locale)}: {formatNumber(count,locale)}</li>)}</ol>
    {data.total===0&&<State title={ar?'لا توجد مراجعات':'No reviews'} body={ar?'تظهر المراجعات بعد عمليات الشراء المحررة فقط.':'Reviews appear only after released purchases.'}/>}
    {data.items.map((item)=><Card key={item.review_ref}><p>{formatNumber(item.rating,locale)}</p><p dir="auto">{item.text}</p>{item.reply&&<><h2>{ar?'رد البائع':'Seller reply'}</h2><p dir="auto">{item.reply}</p></>}<Button type="button" onClick={()=>onReport(item.review_ref)}>{ar?'الإبلاغ عن المراجعة':'Report review'}</Button></Card>)}
    <Button type="button" disabled={data.page===1} onClick={()=>onPage(data.page-1)}>{ar?'السابق':'Previous'}</Button>
    <Button type="button" disabled={data.next_page===null} onClick={()=>{if(data.next_page!==null)onPage(data.next_page);}}>{ar?'التالي':'Next'}</Button>
  </section>;
}
