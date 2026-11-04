'use client';
import { useEffect, useRef } from 'react';
/** A keyed account/resource view cancels transport before any late answer can paint. */
export function useOperationScope() {
  const ref=useRef<{active:boolean;controller:AbortController}|null>(null);
  useEffect(()=>{
    const scope={active:true,controller:new AbortController()}; ref.current=scope;
    return ()=>{scope.active=false;scope.controller.abort();};
  },[]);
  return ()=>{
    if(!ref.current?.active) throw new Error('Operation view is no longer active');
    return ref.current;
  };
}
