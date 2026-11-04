'use client';
import { useQuery } from '@tanstack/react-query';
import { ButtonLink } from '@beirut-time/ui';
import type { SlotContext } from '@/registry-types';
import { buyNowApi } from './api';
import { copy, uuid } from './copy';
// Watch detail supplies its listing id; Orders resolves the single immutable physical fence.
export default function BuyNowSlot({locale,resourceId}:SlotContext){
  const t=copy(locale);
  const current=useQuery({queryKey:['l08-listing-availability',resourceId],queryFn:({signal})=>buyNowApi.listingAvailability(resourceId!,signal),enabled:!!resourceId&&uuid.test(resourceId),retry:false});
  if(!resourceId)return null;
  return <section className="checkout-slot"><h3>{t.eyebrow}</h3>{current.data?.is_demo&&<p>{t.sample}</p>}{current.isPending?<p role="status">{t.loading}</p>:current.error?<p>{t.unavailable}</p>:<p>{current.data?.sale_mode!=='fixed'?t.auction:t[current.data.status]}</p>}{current.data?.status==='available'&&current.data.sale_mode==='fixed'&&<ButtonLink href={`/${locale}/checkout?watch=${encodeURIComponent(current.data.watch_id)}`}>{t.title}</ButtonLink>}</section>;
}
