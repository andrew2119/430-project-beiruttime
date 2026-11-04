export type Unavailable = { kind: 'unavailable'; dependency: string };
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
      const response = await fetch(new URL(path, this.origin), { method, ...requestOptions, signal: AbortSignal.timeout(this.timeoutMs), redirect: 'error', headers, cache: 'no-store' });
      if (response.status >= 500 || response.status === 429) { await response.body?.cancel(); throw new Error('upstream'); }
      const reader = response.body?.getReader(); const chunks: Uint8Array[] = []; let size=0;
      if (reader) while (true) { const next=await reader.read(); if(next.done) break; size+=next.value.byteLength; if(size>maxResponseBytes) { await reader.cancel(); throw new Error('upstream budget'); } chunks.push(next.value); }
      const bytes = new Uint8Array(size); let offset=0; for(const chunk of chunks) { bytes.set(chunk,offset); offset+=chunk.byteLength; }
      this.failures = this.openedAt = 0;
      const cleanHeaders=new Headers(response.headers); for(const name of ['Content-Encoding','Content-Length','Transfer-Encoding']) cleanHeaders.delete(name);
      return new Response([204,304].includes(response.status) || method==='HEAD' ? null : bytes, {status:response.status,headers:cleanHeaders});
    } catch { if (++this.failures >= 3 || halfOpen) this.openedAt = Date.now(); return { kind: 'unavailable', dependency: this.name }; }
    finally { this.active--; this.probing = false; }
  }
}
