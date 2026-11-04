'use client';
import { useEffect, useState, type ComponentType } from 'react';
import { slotsFor } from '@/registry-loader';
import { useAccessContext } from '@/shell/access-context';
import type { SlotContext } from '@/registry-types';
import type { Locale } from '@beirut-time/i18n';
import { SlotBoundary } from './slot-boundary';
import en from './en.json';
import ar from './ar.json';
const entries=slotsFor('watch.detail');
type Loaded={id:string;component:ComponentType<SlotContext>|null};
// Mount only after the parent has a current public, available listing. Optional
// modules own authorization/commands; an access rotation remounts private controls.
export function WatchSlots({id,locale}:{id:string;locale:Locale}) {
  const t=locale==='ar'?ar:en,access=useAccessContext();
  const [loaded,setLoaded]=useState<Loaded[]|null>(entries.length?null:[]);
  useEffect(()=>{
    let disposed=false;
    void Promise.all(entries.map(async slot=>{
      try{return {id:slot.id,component:(await slot.load()).default};}
      catch{return {id:slot.id,component:null};}
    })).then(result=>{if(!disposed)setLoaded(result);});
    return ()=>{disposed=true;};
  },[]);
  if(!loaded)return <p role="status" className="discovery-help">{t.slotLoading}</p>;
  return <>{loaded.map(({id:slotId,component:Slot})=>Slot?<SlotBoundary key={`${slotId}:${access.fingerprint??'public'}`} fallback={t.slotUnavailable}><Slot locale={locale} resourceId={id} accessFingerprint={access.fingerprint??undefined}/></SlotBoundary>:<p className="notice" key={slotId}>{t.slotUnavailable}</p>)}</>;
}
