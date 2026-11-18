function isPublicationPending(bytes: Uint8Array): boolean {
  try {
    const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    const record = (item: unknown): item is Record<string, unknown> => item !== null && typeof item === 'object' && !Array.isArray(item);
    if (!record(value) || Object.keys(value).length !== 1 || !record(value.error)) return false;
    const error = value.error;
    return Object.keys(error).length === 4 && error.code === 'publication_review_pending'
      && typeof error.message === 'string' && [...error.message].length <= 500
      && typeof error.request_id === 'string' && error.request_id.length > 0 && error.request_id.length <= 200
      && record(error.details);
  } catch { return false; }
}

export type Unavailable = { kind: 'unavailable'; dependency: string };
const credentialPaths = new Set(['login', 'register', 'reauthenticate', 'password', 'reset', 'refresh'].map(operation => `/v1/accounts/${operation}`));
// Independent per-dependency budgets; bounded body/deadline, no retry or waiting queue.
export class Dependency {
  active = 0; failures = 0; openedAt = 0; probing = false;
  constructor(readonly name: string, readonly origin: string, readonly timeoutMs = 1200, readonly concurrency = 4, readonly cooldownMs = 10000) {}
  get(path: string, requestId: string) { return this.request('GET',path,requestId); }
  async request(method: string, path: string, requestId: string, options: { headers?: HeadersInit; body?: BodyInit; maxResponseBytes?: number } = {}): Promise<Response | Unavailable> {
    const halfOpen = this.openedAt !== 0;
    if (this.active >= this.concurrency || (halfOpen && (Date.now() - this.openedAt < this.cooldownMs || this.probing))) return { kind: 'unavailable', dependency: this.name };
    this.active++; if (halfOpen) this.probing = true;
    try {
      const headers = new Headers(options.headers); headers.set('X-Request-ID',requestId);
      const {maxResponseBytes=2*1024*1024,...requestOptions}=options;
      const url = new URL(path, this.origin);
      // Password hashing needs a separate bounded budget, including during busy periods.
      const timeoutMs = this.name === 'identity' && method === 'POST' && credentialPaths.has(url.pathname) ? 8000 : this.timeoutMs;
      const response = await fetch(url, { method, ...requestOptions, signal: AbortSignal.timeout(timeoutMs), redirect: 'error', headers, cache: 'no-store' });
      const pendingCandidate = this.name === 'catalog' && method === 'POST'
        && /^\/v1\/seller\/listings\/[A-Za-z0-9_-]{1,200}\/publish$/.test(url.pathname)
        && response.status === 503 && response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() === 'application/json';
      const responseLimit = pendingCandidate ? Math.min(maxResponseBytes, 16 * 1024) : maxResponseBytes;
      if ((response.status >= 500 && !pendingCandidate) || response.status === 429) { await response.body?.cancel(); throw new Error('upstream'); }
      const reader = response.body?.getReader(); const chunks: Uint8Array[] = []; let size=0;
      if (reader) while (true) { const next=await reader.read(); if(next.done) break; size+=next.value.byteLength; if(size>responseLimit) { await reader.cancel(); throw new Error('upstream budget'); } chunks.push(next.value); }
      const bytes = new Uint8Array(size); let offset=0; for(const chunk of chunks) { bytes.set(chunk,offset); offset+=chunk.byteLength; }
      if (pendingCandidate && !isPublicationPending(bytes)) throw new Error('upstream envelope');
      this.failures = this.openedAt = 0;
      const cleanHeaders=new Headers(response.headers); for(const name of ['Content-Encoding','Content-Length','Transfer-Encoding']) cleanHeaders.delete(name);
      return new Response([204,304].includes(response.status) || method==='HEAD' ? null : bytes, {status:response.status,headers:cleanHeaders});
    } catch { if (++this.failures >= 3 || halfOpen) this.openedAt = Date.now(); return { kind: 'unavailable', dependency: this.name }; }
    finally { this.active--; this.probing = false; }
  }
}
