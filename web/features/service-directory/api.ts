import { useEffect, useRef, useState } from 'react';
import { authenticatedRequest } from '@/features/identity/session';
import { useAccessContext } from '@/shell/access-context';
import { ApiError } from '@/lib/api/client';
// Identity owns coordinated refresh and memory-only credentials.
export const privateRequest = authenticatedRequest;
export const directoryPath = '/api/web/v1/service-operations/v1/directory';
export const movementPath = '/api/web/v1/catalog/v1/options/movement';

// An uncertain retry reuses the logical command key and original body.
export function useJsonCommand() {
  const { fingerprint } = useAccessContext();
  const attempt = useRef<{path:string;body:string;key:string;uncertain?:boolean}|null>(null);
  const active = useRef(new Set<AbortController>());
  useEffect(() => {
    const requests = active.current;
    const abort = () => { requests.forEach(controller=>controller.abort()); requests.clear(); attempt.current=null; };
    window.addEventListener('bt:access-change',abort);
    return () => { window.removeEventListener('bt:access-change',abort); abort(); };
  },[]);
  return async <T,>(path:string, body:unknown, method:'POST'|'PUT'='POST'):Promise<T> => {
    if (!fingerprint) throw new ApiError(401,'unauthorized','');
    const encoded = JSON.stringify(body);
    if (attempt.current?.uncertain && (attempt.current.path!==path || attempt.current.body!==encoded)) throw new ApiError(409,'pending_operation','');
    if (!attempt.current || attempt.current.path!==path || attempt.current.body!==encoded) {
      attempt.current = {path,body:encoded,key:crypto.randomUUID()};
    }
    attempt.current.uncertain=true;
    const currentAttempt=attempt.current;
    const controller = new AbortController();
    active.current.add(controller);
    try {
      const result = await privateRequest<T>(path,{method,accessFingerprint:fingerprint,signal:controller.signal,headers:{'Content-Type':'application/json','Idempotency-Key':attempt.current.key},body:encoded});
      if(controller.signal.aborted) throw new DOMException('Access context changed.','AbortError');
      currentAttempt.uncertain=false;
      return result;
    } catch(error) {
      if (error instanceof ApiError && error.status>=400 && error.status<500) currentAttempt.uncertain=false;
      throw error;
    } finally { active.current.delete(controller); }
  };
}

export function useCommandMutation<T>({mutationFn,onSuccess}:{mutationFn:()=>Promise<T>;onSuccess?:(value:T)=>void}) {
  const [state,setState]=useState<{isPending:boolean;isError:boolean;isSuccess:boolean;needsRecovery:boolean;error:unknown;data?:T}>({isPending:false,isError:false,isSuccess:false,needsRecovery:false,error:null});
  const busy=useRef(false);
  const recovery=useRef<(()=>Promise<T>)|null>(null);
  return {...state, reset:()=>{if(!busy.current&&!recovery.current)setState({isPending:false,isError:false,isSuccess:false,needsRecovery:false,error:null});},mutate:()=>{
    if(busy.current)return;
    busy.current=true;setState({isPending:true,isError:false,isSuccess:false,needsRecovery:false,error:null});
    const action=recovery.current??mutationFn;
    void action().then(data=>{recovery.current=null;setState({isPending:false,isError:false,isSuccess:true,needsRecovery:false,error:null,data});onSuccess?.(data);},error=>{const needsRecovery=error instanceof ApiError&&error.status>=500;recovery.current=needsRecovery?action:null;setState({isPending:false,isError:true,isSuccess:false,needsRecovery,error});}).finally(()=>{busy.current=false;});
  }};
}
