'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { PrivateConsent } from '@contracts/contracts-eligibility/consent';
import { consentRead } from './reads';
import { ApiError } from '@/lib/api/client';
type Answer={consents:PrivateConsent[];total:number;page:number};
/** Compatibility for routes outside the shared read scope. No cross-visit cache. */
export function useConsentRead(fingerprint:string,page:number) {
  const read=useMemo(()=>consentRead(fingerprint,page),[fingerprint,page]);
  const [answer,setAnswer]=useState<Answer|null>(null),[error,setError]=useState<unknown>(null);
  const [refresh,setRefresh]=useState(0),[settled,setSettled]=useState<{read:typeof read;refresh:number}|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    void read.ask(controller.signal).then(value=>{
      if(!controller.signal.aborted){setAnswer(value);setError(null);}
    }).catch(failure=>{
      if(!controller.signal.aborted){
        setError(failure);
        if(failure instanceof ApiError&&failure.status<500&&failure.status!==408&&failure.status!==429)setAnswer(null);
      }
    }).finally(()=>{
      if(!controller.signal.aborted)setSettled({read,refresh});
    });
    return ()=>controller.abort();
  },[read,refresh]);
  const refetch=useCallback(()=>setRefresh(value=>value+1),[]);
  const denied=error instanceof ApiError&&(error.status===401||error.status===403);
  return {denied,data:answer?.page===page?answer:undefined,error,refetch,isFetching:settled?.read!==read||settled.refresh!==refresh};
}
