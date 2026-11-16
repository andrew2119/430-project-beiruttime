import type { ErrorEnvelope } from './types';
export class ApiError extends Error {
  constructor(public status: number, public code: string, public requestId: string, public details: Record<string,unknown> = {}) { super(code); }
}
// One invocation deadline, body-read budget and support reference.
// Identity owns coordinated refresh; no credential or private response is persisted here.
async function invoke<T>(path: string, options: RequestInit, format: 'json'|'blob'): Promise<T> {
  if(!path.startsWith('/api/')) throw new ApiError(400,'invalid_api_path','');
  const deadline=AbortSignal.timeout(4000);
  const signal=options.signal?AbortSignal.any([deadline,options.signal]):deadline;
  const headers=new Headers(options.headers);
  if(!headers.has('Accept')) headers.set('Accept',format==='blob'?'application/octet-stream':'application/json');
  headers.set('X-Request-ID',crypto.randomUUID());
  try {
    const response=await fetch(path,{...options,headers,signal,cache:'no-store',credentials:'same-origin'});
    if(!response.ok) {
      let envelope:Partial<ErrorEnvelope>={};
      try { envelope=await response.json(); } catch { /* Never display an untrusted HTML/text error. */ }
      const details=envelope.error?.details;
      throw new ApiError(response.status,envelope.error?.code??'http_error',envelope.error?.request_id??response.headers.get('X-Request-ID')??'',details&&typeof details==='object'&&!Array.isArray(details)?details:{});
    }
    return (format==='blob'?await response.blob():await response.json()) as T;
  } catch(error) {
    if(error instanceof ApiError||options.signal?.aborted) throw error;
    throw new ApiError(503,'unavailable','');
  }
}
export function request<T>(path: string, options: RequestInit = {}): Promise<T> { return invoke<T>(path,options,'json'); }
export function requestBlob(path: string, options: RequestInit = {}): Promise<Blob> { return invoke<Blob>(path,options,'blob'); }
