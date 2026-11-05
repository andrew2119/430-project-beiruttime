'use client';
import { useQuery } from '@tanstack/react-query';
import { request } from '@/lib/api/client';
import type { SlotContext } from '@/registry-types';
import { ButtonLink } from '@beirut-time/ui';
import { useQuoteCopy } from '@/features/pricing/s2-shared';
export default function WatchOffer({resourceId,locale}:SlotContext){
 const {t}=useQuoteCopy();const listing=useQuery({queryKey:['l14','watch-offer',resourceId],enabled:!!resourceId,queryFn:({signal})=>request<{status:string;facts:{sale_mode:string}}>(`/api/web/v1/catalog/v1/listings/${resourceId}`,{signal})});
 if(!listing.data||listing.data.status!=='published'||listing.data.facts.sale_mode!=='fixed_price')return null;
 return <ButtonLink variant="outline" href={`/${locale}/offers?listing=${encodeURIComponent(resourceId!)}`}>{t.newOffer}</ButtonLink>;
}
