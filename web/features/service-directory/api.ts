import { useEffect, useRef } from 'react';
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
  const attempt = useRef<{path:string;body:string;key:string}|null>(null);
  const active = useRef(new Set<AbortController>());
  useEffect(() => {
    const requests = active.current;
    const abort = () => { requests.forEach(controller=>controller.abort()); requests.clear(); attempt.current=null; };
    window.addEventListener('bt:access-change',abort);
    return () => { window.removeEventListener('bt:access-change',abort); abort(); };
  },[]);
  return async <T,>(path:string, body:unknown):Promise<T> => {
    if (!fingerprint) throw new ApiError(401,'unauthorized','');
    const encoded = JSON.stringify(body);
    if (!attempt.current || attempt.current.path!==path || attempt.current.body!==encoded) {
      attempt.current = {path,body:encoded,key:crypto.randomUUID()};
    }
    const controller = new AbortController();
    active.current.add(controller);
    try {
      const result = await privateRequest<T>(path,{method:'POST',accessFingerprint:fingerprint,signal:controller.signal,headers:{'Content-Type':'application/json','Idempotency-Key':attempt.current.key},body:encoded});
      if(controller.signal.aborted) throw new DOMException('Access context changed.','AbortError');
      return result;
    } finally { active.current.delete(controller); }
  };
}
