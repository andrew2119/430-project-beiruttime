'use client';
import { useEffect, useState } from 'react';
import { slotsFor } from '@/registry-loader';
import { useAccessContext } from '@/shell/access-context';
import type { Locale } from '@beirut-time/i18n';
import { SlotBoundary } from './slot-boundary';
import en from './en.json';
import ar from './ar.json';
import { loadWatchSlots, slotMountKey, type LoadedSlot } from './slot-loader';
const entries=slotsFor('watch.detail');
// Mount only after the parent has a current public, available listing. Optional
// modules own authorization/commands; an access rotation remounts private controls.
export function WatchSlots({id,locale}:{id:string;locale:Locale}) {
  const t=locale==='ar'?ar:en,access=useAccessContext();
  const [loaded,setLoaded]=useState<LoadedSlot[]|null>(entries.length?null:[]);
  useEffect(()=>{
    let disposed=false;
    void loadWatchSlots(entries).then(result=>{if(!disposed)setLoaded(result);});
    return ()=>{disposed=true;};
  },[]);
  if(!loaded)return <p role="status" className="discovery-help">{t.slotLoading}</p>;
  return <>{loaded.map(({id:slotId,component:Slot})=>Slot?<SlotBoundary key={slotMountKey(slotId,access.fingerprint)} fallback={t.slotUnavailable}><Slot locale={locale} resourceId={id} accessFingerprint={access.fingerprint??undefined}/></SlotBoundary>:<p className="notice" key={slotId}>{t.slotUnavailable}</p>)}</>;
}
