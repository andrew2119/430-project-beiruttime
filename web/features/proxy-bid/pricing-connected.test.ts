import {describe,expect,it,vi} from 'vitest';
import {ApiError} from '@/lib/api/client';
import {previewMaximum,reviewMaximum} from './maximum-api';
const live=vi.hoisted(()=>({token:'',fingerprint:''}));
const pricing=process.env.BT_L06_PRICING_URL??'http://127.0.0.1:8104';
const identity=process.env.BT_L06_IDENTITY_URL??'http://127.0.0.1:8101';
const origin=process.env.BT_L06_IDENTITY_ORIGIN??'http://localhost:3000';
vi.mock('./session',()=>({authenticatedRequest:async(path:string,options:RequestInit&{accessFingerprint?:string}={})=>{
  const {accessFingerprint,...init}=options;
  if(accessFingerprint!==live.fingerprint) throw new ApiError(401,'unauthorized','');
  if(!path.startsWith('/api/web/v1/pricing/')) throw new Error('Unexpected connected proof destination');
  const headers=new Headers(options.headers);headers.set('Authorization',`Bearer ${live.token}`);
  const response=await fetch(`${pricing}${path.slice('/api/web/v1/pricing'.length)}`,{
    ...init,headers,signal:options.signal??AbortSignal.timeout(4000),
  });
  if(!response.ok) {
    const body=await response.json().catch(()=>({}));
    throw new ApiError(response.status,body.error?.code??'http_error','');
  }
  return response.json();
}}));
type Buyer={id:string;token:string;cookie:string;fingerprint:string};
async function register():Promise<Buyer> {
  const response=await fetch(`${identity}/v1/accounts/register`,{method:'POST',signal:AbortSignal.timeout(4000),
    headers:{Origin:origin,'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},
    body:JSON.stringify({email:`bt-l06-fee-${crypto.randomUUID()}@example.invalid`,password:crypto.randomUUID()+crypto.randomUUID(),display_name:'Sample buyer fee check'}),
  });
  if(!response.ok) throw new Error(`Sample buyer registration failed (${response.status})`);
  const body=await response.json();
  if(!body.access_token||!body.account?.id||!body.access_fingerprint) throw new Error('No live buyer session returned');
  return {id:body.account.id,token:body.access_token,fingerprint:body.access_fingerprint,cookie:(response.headers.get('set-cookie')??'').split(';')[0]};
}
async function logout(buyer:Buyer) {
  const response=await fetch(`${identity}/v1/accounts/logout`,{method:'POST',signal:AbortSignal.timeout(4000),
    headers:{Origin:origin,Cookie:buyer.cookie,Authorization:`Bearer ${buyer.token}`}});
  if(!response.ok) throw new Error(`Sample session cleanup failed (${response.status})`);
}
/** Explicit opt-in: real Identity/Pricing databases, no transport response fixtures.
 * The subject is a proposed, non-binding reference, NOT an acknowledged Auction.
 * This proves quotes/review/owner scope only; it cannot prove a real bid outcome.
 */
describe.skipIf(process.env.BT_L06_CONNECTED_PRICING!=='1')('connected non-binding fee preview',()=>{
  it('persists the exact sample preview/review privately and grants no reservation authority',async()=>{
    const buyers:Buyer[]=[];
    try {
      buyers.push(await register());buyers.push(await register());
      const [owner,other]=buyers;live.token=owner.token;live.fingerprint=owner.fingerprint;
      const proposed={id:crypto.randomUUID(),revision:1,currency:'USD' as const};
      const quote=await previewMaximum(proposed,800000,{subjectId:owner.id,accessFingerprint:owner.fingerprint},AbortSignal.timeout(4000),crypto.randomUUID());
      expect(quote.sample).toBe(true);expect(quote.buyer_fee_minor).toBe(24000);expect(quote.total_minor).toBe(824000);
      await reviewMaximum(quote,crypto.randomUUID(),AbortSignal.timeout(4000));
      const read=await fetch(`${pricing}/v1/quotes/${quote.fee_quote_id}`,{headers:{Authorization:`Bearer ${owner.token}`},signal:AbortSignal.timeout(4000)});
      expect(read.status).toBe(200);
      const retained=await read.json();
      expect(retained.price_minor).toBe(800000);expect(retained.purpose).toBe('bid');
      expect(Boolean(retained.reviewed_at)).toBe(true);expect(retained.source_verified).toBe(false);
      const denied=await fetch(`${pricing}/v1/quotes/${quote.fee_quote_id}`,{headers:{Authorization:`Bearer ${other.token}`},signal:AbortSignal.timeout(4000)});
      expect([403,404].includes(denied.status)).toBe(true);
      const reservation=await fetch(`${pricing}/internal/v1/quotes/${quote.fee_quote_id}/validation`,{headers:{Authorization:`Bearer ${owner.token}`},signal:AbortSignal.timeout(4000)});
      expect(reservation.ok).toBe(false);
      const result=await reservation.json();expect(result.error?.code).toBe('quote_not_authoritative');
    } finally {
      live.token='';live.fingerprint='';
      for(const buyer of buyers) await logout(buyer);
    }
  },15000);
});
