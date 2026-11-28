'use client';
import { useState } from 'react';
import { Avatar, ImageFrame, Button, ButtonLink, Card, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { useSellerRead, useSellerRefresh } from './read';
import { usePageRead } from '@/lib/page-speed/read';
import { copy } from './copy';
import { replacePageQuery } from '@/lib/page-speed/address';

export default function SellerProfile({id,initialPage=1}:{id:string;initialPage?:number}) {
 const locale=useLocale(), t=copy[locale];
 const [page,setPage]=useState(initialPage);
 const changePage=(next:number)=>{replacePageQuery({page:String(next)});setPage(next);};
 const read=useSellerRead(id,page);
 const query=usePageRead(read);
 useSellerRefresh(query.refetch,read!==null);
 const data=query.data;
 const busy=query.isPending || query.isFetching;
 const previousBlocked=busy || page===1;
 const nextBlocked=busy || data?.listings.state!=='ready' || page*20>=(data.listings.total??0);
 // The native ref exposes blocked semantics without disabling the focused control.
 const controls=<nav aria-label={t.listings}>
  <Button ref={node=>{node?.setAttribute('aria-disabled',String(busy));}} onClick={()=>{if (!busy) void query.refetch();}}>{t.retry}</Button>
  <Button ref={node=>{node?.setAttribute('aria-disabled',String(previousBlocked));}} onClick={()=>{if (!previousBlocked) changePage(page-1);}}>{t.previous}</Button>
  <Button ref={node=>{node?.setAttribute('aria-disabled',String(nextBlocked));}} onClick={()=>{if (!nextBlocked) changePage(page+1);}}>{t.next}</Button>
 </nav>;
 const state=(value:string)=>value==='denied'?t.denied:value==='pending'?t.pending:value==='stale'?t.stale:t.unavailable;
 const identity=!query.isError && !query.isFetching && data?.state==='ready'?data.identity:null;

 return <PageFrame><PageHeader title={t.title} actions={controls}/><PageBody>
 {query.isPending?<PageLoading label={t.loading}/>:
 !identity || !data?<State kind={query.isFetching?'loading':'error'} title={state(query.error instanceof ApiError && query.error.status===403?'denied':query.error instanceof ApiError && query.error.status===409?'stale':data?.state??'unavailable')} body={t.recovery}>{data?.operation_id && <p><bdi>{data.operation_id}</bdi></p>}</State>:
 <><Card>{identity.banner && <ImageFrame src={identity.banner} alt={identity.name} width={960} height={240} placeholder={<span>{identity.name}</span>}/>}<Avatar name={identity.name} label={identity.name} src={identity.logo}/><h2 className="bt-heading"><bdi>{identity.name}</bdi></h2><p>{t[identity.kind]}</p><p>{t[identity.verification]}</p><p>{t.city}: <bdi>{identity.city??t.missing}</bdi></p><p>{t.since}: <time dateTime={identity.member_since}>{new Intl.DateTimeFormat(locale,{timeZone:'UTC',year:'numeric',month:'long',day:'numeric',numberingSystem:locale==='ar'?'arab':'latn'}).format(new Date(identity.member_since))}</time></p></Card>
 <Card><h2 className="bt-heading">{t.sales}</h2>{data.sales.state==='ready'?<p>{data.sales.released_count===0?t.none:formatNumber(data.sales.released_count,locale)}</p>:<State kind="error" title={state(data.sales.state)} body={t.recovery}></State>}</Card>
 <Card><h2 className="bt-heading">{t.reviews}</h2>{data.reviews.state==='ready' && data.reviews.distribution?<>{data.reviews.distribution.every(n=>n===0)?<p>{t.noReviews}</p>:<ul>{data.reviews.distribution.map((n,index)=><li key={index}>{t.stars} {formatNumber(index+1,locale)}: {formatNumber(n,locale)}</li>)}</ul>}</>:<State kind="error" title={state(data.reviews.state)} body={t.recovery}></State>}</Card>
 <Card><h2 className="bt-heading">{t.listings}</h2>{data.listings.state==='ready'?<><p>{t.total}: {formatNumber(data.listings.total,locale)}</p>{data.listings.items.length?<ul>{data.listings.items.map(item=><li key={item.id}><ButtonLink href={`/${locale}/watches/${encodeURIComponent(item.id)}`}><bdi>{item.title}</bdi></ButtonLink></li>)}</ul>:<p>{t.empty}</p>}</>:<State kind="error" title={state(data.listings.state)} body={t.recovery}></State>}</Card></>}
 </PageBody></PageFrame>;
}
