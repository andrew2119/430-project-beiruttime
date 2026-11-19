'use client';
import { useEffect, useState } from 'react';
import { definePageRead } from '@/lib/page-speed/definition';
import { request } from '@/lib/api/client';
import { validateProfile } from './validate';
import { useAccessContext } from '@/shell/access-context';
import { replacePageQuery } from '@/lib/page-speed/address';
export const sellerRead = definePageRead({
 key:(id:string,page:number,operation:string)=>['public-profile.v1',id,page,operation],
 ask:(signal,id,page,operation)=>request<unknown>(`/api/web/v1/identity/public-profiles/${encodeURIComponent(id)}?page=${page}&operation_id=${encodeURIComponent(operation)}`,{signal}).then(value=>validateProfile(value,id,page,operation)),
 warm:'open-only', fresh:0,
});
/** The shared scope owns cancellation and access-bound answers. */
export function useSellerRead(id:string,page:number) {
 const scope=useAccessContext().fingerprint;
 const [reference,setReference]=useState<{id:string;page:number;scope:string|null;operation:string}|null>(null);
 const current=reference?.id===id && reference.page===page && reference.scope===scope?reference:null;
 useEffect(()=>{
  if (current) return;
  const saved=new URL(window.location.href).searchParams.getAll('profile_read');
  const operation=!reference && saved.length===1 && /^[a-zA-Z0-9-]{1,80}$/.test(saved[0]) ? saved[0] : crypto.randomUUID();
  replacePageQuery({profile_read:operation});
  let active=true;
  queueMicrotask(()=>{if (active) setReference({id,page,scope,operation});});
  return ()=>{active=false;};
 },[id,page,scope,current,reference]);
 return current?sellerRead(id,page,current.operation):null;
}

export function useSellerRefresh(refetch:()=>unknown,enabled:boolean) {
 useEffect(()=>{
  const refresh=()=>{if (enabled) void refetch();};
  window.addEventListener('bt:access-change',refresh);
  window.addEventListener('focus',refresh);
  return ()=>{window.removeEventListener('bt:access-change',refresh);window.removeEventListener('focus',refresh);};
 },[enabled,refetch]);
}
