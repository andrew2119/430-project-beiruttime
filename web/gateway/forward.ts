import { gatewayRegistrations } from '@/registry-loader';
import { dependencies, requestId, privateHeaders, serviceNames } from '@/lib/bff/status';
import type { ServiceName } from '@/lib/api/types';
import type { Role } from '@/registry-types';
import { validatedBrowserOrigin } from './origin';

function error(status: number, code: string, id: string) {
  return Response.json({ error: { code, message: status===503 ? 'Service is temporarily unavailable.' : 'The request could not be completed.', request_id:id, details:{} } },{status,headers:privateHeaders(id)});
}
export function pathMatches(pattern: string, parts: string[]) {
  const expected=pattern.split('/').slice(1);
  return parts.length===expected.length && parts.every((part,i)=>/^[A-Za-z0-9_.-]{1,200}$/.test(part) && part!=='.' && part!=='..' && (expected[i].startsWith(':') || part===expected[i]));
}
async function readBody(request: Request, maxBytes: number) {
  const reader=request.body?.getReader(); if(!reader) return undefined;
  const chunks:Uint8Array[]=[]; let size=0;
  while(true) { const next=await reader.read(); if(next.done) break; size+=next.value.length; if(size>maxBytes) { await reader.cancel(); throw new Error('body budget'); } chunks.push(next.value); }
  const bytes=new Uint8Array(size); let offset=0; for(const chunk of chunks) { bytes.set(chunk,offset); offset+=chunk.length; } return bytes;
}
export async function forward(request: Request, context: { params: Promise<{ service: string; path: string[] }> }) {
  const id=requestId(request); const {service,path}=await context.params;
  if(!serviceNames.includes(service as ServiceName)) return error(404,'not_found',id);
  const endpoint=gatewayRegistrations.find(e=>e.service===service && e.methods.includes(request.method as 'GET') && pathMatches(e.path,path));
  if(!endpoint) return error(404,'not_found',id);
  const validatedOrigin=validatedBrowserOrigin(request);
  if(!['GET','HEAD'].includes(request.method) && !validatedOrigin) return error(403,'invalid_origin',id);
  const authorization=request.headers.get('Authorization');
  if(!endpoint.roles.includes('public')) {
    if(!authorization?.startsWith('Bearer ')) return error(401,'unauthorized',id);
    const identity=await dependencies.get('identity')!.request('GET','/internal/v1/principal',id,{headers:{Authorization:authorization}});
    if(!(identity instanceof Response)) return error(503,'unavailable',id);
    if(!identity.ok) return error(401,'unauthorized',id);
    let roles:Role[]=[];
    try { const principal=await identity.json(); if(!principal.actor?.subject_id || !Array.isArray(principal.roles)) return error(401,'unauthorized',id); roles=principal.roles; } catch { return error(503,'unavailable',id); }
    if(!endpoint.roles.some(role=>roles.includes(role))) return error(403,'forbidden',id);
  }
  const headers=new Headers();
  // Identity's own CSRF guard must receive the browser origin already validated here.
  if(validatedOrigin) headers.set('Origin',validatedOrigin);
  for(const key of ['Authorization','Content-Type','Idempotency-Key','If-Match','Accept-Language']) { const value=request.headers.get(key); if(value) headers.set(key,value); }
  if(service==='identity' && endpoint.forwardCookies?.length) {
    const allowed=endpoint.forwardCookies;
    const cookies=(request.headers.get('Cookie')??'').split(';').filter(c=>allowed.includes(c.trim().split('=')[0]));
    if(cookies.length) headers.set('Cookie',cookies.join(';'));
  }
  let body:Uint8Array|undefined;
  try { if(!['GET','HEAD'].includes(request.method)) body=await readBody(request,endpoint.maxBodyBytes??1024*1024); } catch { return error(413,'body_too_large',id); }
  const query=new URL(request.url).search;
  const upstream=await dependencies.get(service as ServiceName)!.request(request.method,'/'+path.map(encodeURIComponent).join('/')+query,id,{headers,body:body as BodyInit|undefined,maxResponseBytes:endpoint.maxResponseBytes});
  if(!(upstream instanceof Response)) return error(503,'unavailable',id);
  const responseHeaders=new Headers(privateHeaders(id));
  responseHeaders.set('Content-Type',upstream.headers.get('Content-Type')??'application/json');
  if(service==='identity' && endpoint.forwardCookies?.length) for(const cookie of upstream.headers.getSetCookie()) responseHeaders.append('Set-Cookie',cookie);
  return new Response(upstream.body,{status:upstream.status,headers:responseHeaders});
}
