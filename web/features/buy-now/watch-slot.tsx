'use client';
import { useQuery } from '@tanstack/react-query';
import { ButtonLink, Card } from '@beirut-time/ui';
import { ShoppingBag } from 'lucide-react';
import { CardHead, LoadingRows, SectionState } from '@beirut-time/ui';
import type { SlotContext } from '@/registry-types';
import { buyNowApi } from './api';
import { copy, uuid } from './copy';
// Watch detail supplies its listing id; Orders resolves the single immutable physical fence.
export default function BuyNowSlot({locale,resourceId}:SlotContext){
  const t=copy(locale);
  const current=useQuery({queryKey:['l08-listing-availability',resourceId],queryFn:({signal})=>buyNowApi.listingAvailability(resourceId!,signal),enabled:!!resourceId&&uuid.test(resourceId),retry:false});
  if(!resourceId)return null;
  return <Card className="checkout-slot"><CardHead title={t.eyebrow} icon={ShoppingBag}/>{current.data?.is_demo&&<p>{t.sample}</p>}{current.isPending?<LoadingRows label={t.loading}/>:current.error?<SectionState title={t.unavailable} kind="error"/>:<p>{current.data?.sale_mode!=='fixed'?t.auction:t[current.data.status]}</p>}{current.data?.status==='available'&&current.data.sale_mode==='fixed'&&<ButtonLink size="sm" href={`/${locale}/checkout?listing_id=${encodeURIComponent(current.data.listing_id)}`}>{t.title}</ButtonLink>}</Card>;
}
