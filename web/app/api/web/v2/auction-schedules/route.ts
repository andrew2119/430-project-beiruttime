import {forward,readBody} from '@/gateway/forward';
import {validatedBrowserOrigin} from '@/gateway/origin';
import {CivilTimeError,interpretBeirut} from '@/gateway/beirut-time';
export const dynamic='force-dynamic';
const headers={'Cache-Control':'no-store'};
function failure(code:string,status=422){return Response.json({error:{code,message:'Review the Beirut schedule before confirming.',details:{}}},{status,headers});}
export async function POST(request:Request){
  if(!validatedBrowserOrigin(request))return failure('invalid_origin',403);
  if(!request.headers.get('Authorization')?.startsWith('Bearer '))return failure('unauthorized',401);
  let bytes:Uint8Array|undefined;
  try{bytes=await readBody(request,64*1024);}catch{return failure('body_too_large',413);}
  let input:Record<string,unknown>;
  try{const parsed:unknown=JSON.parse(new TextDecoder().decode(bytes));if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return failure('invalid_schedule');input=parsed as Record<string,unknown>;}catch{return failure('invalid_schedule');}
  try{
    if('extension_policy' in input||'buy_now_minor' in input)return failure('fixed_end_policy');
    const allowed=new Set(['starts_local','ends_local','review_only','confirmed_starts_at','confirmed_ends_at','listing_id','currency','opening_minor','reserve_minor','increment_bands']);
    if(Object.keys(input).some(key=>!allowed.has(key)))return failure('invalid_schedule');
    const starts=interpretBeirut(input.starts_local),ends=interpretBeirut(input.ends_local);
    if(ends.utc<=starts.utc||Date.parse(ends.utc)-Date.parse(starts.utc)>90*86400000)return failure('invalid_schedule');
    if(input.review_only===true)return Response.json({starts,ends},{headers});
    if(input.currency!=='USD')return failure('currency_not_supported');
    if(input.confirmed_starts_at!==starts.utc||input.confirmed_ends_at!==ends.utc)return failure('schedule_review_required');
    const body={listing_id:input.listing_id,currency:'USD',opening_minor:input.opening_minor,reserve_minor:input.reserve_minor,
      increment_bands:input.increment_bands,starts_at:starts.utc,ends_at:ends.utc};
    const url=new URL(request.url);url.pathname='/api/web/v1/auction/v1/auctions';
    const forwarded=new Request(url,{method:'POST',headers:request.headers,body:JSON.stringify(body),signal:request.signal});
    // Reuse existing current-principal, origin, service bulkhead and permission enforcement.
    return forward(forwarded,{params:Promise.resolve({service:'auction',path:['v1','auctions']})});
  }catch(error){if(error instanceof CivilTimeError)return failure(error.code);throw error;}
}
