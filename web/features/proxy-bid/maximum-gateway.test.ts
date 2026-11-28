import {expect,it,vi} from 'vitest';
import {forward} from '@/gateway/forward';
import {lookupMaximum,readOwnMaximum,sendMaximum,type MaximumIntent} from './maximum-api';

const actorId='00000000-0000-4000-8000-000000000005';
const upstream=vi.hoisted(()=>vi.fn());
vi.mock('@/registry-loader',async()=>{
  const {default:buyer}=await import('@/registrations/L06');
  return {gatewayRegistrations:buyer.gateway};
});
vi.mock('@/gateway/origin',()=>({validatedBrowserOrigin:()=> 'https://example.invalid'}));
vi.mock('@/lib/bff/status',()=>({
  dependencies:new Map([
    ['identity',{request:async()=>Response.json({actor:{subject_id:actorId},roles:['buyer']})}],
    ['auction',{request:upstream}],
  ]),
  serviceNames:['auction'],
  requestId:()=> 'test-maximum-gateway',
  privateHeaders:()=>({'Cache-Control':'no-store'}),
}));
vi.mock('./session',()=>({
  authenticatedRequest:async(path:string,init:RequestInit)=>{
    const url=new URL(path,'https://example.invalid');
    const [, , , , service, ...parts]=url.pathname.split('/');
    const headers=new Headers(init.headers);
    headers.set('Authorization','Bearer synthetic-gateway');
    const response=await forward(new Request(url,{...init,headers}),{params:Promise.resolve({service,path:parts})});
    if(!response.ok) throw new Error('Request failed: '+response.status);
    return response.json();
  },
}));

it('forwards versioned ceiling and receipt operations through the registered buyer route',async()=>{
  const auctionId='00000000-0000-4000-8000-000000000001';
  const watchId='00000000-0000-4000-8000-000000000002';
  const owner={subjectId:actorId,accessFingerprint:'test-scope'};
  const intent:MaximumIntent={key:'00000000-0000-4000-8000-000000000003',amount_minor:450000,
    fee_quote_id:'00000000-0000-4000-8000-000000000004',revision:2,owner:owner.accessFingerprint,
    actor_id:owner.subjectId,watch_id:watchId,quote_revision:1,policy_revision:'test-policy'};
  const receipt={schema_version:2,operation_id:intent.key,subject_id:auctionId,actor_id:owner.subjectId,
    organization_id:null,watch_id:watchId,expected_revision:2,revision:3,quote_id:intent.fee_quote_id,
    quote_revision:1,policy_revision:intent.policy_revision,state:'accepted',pending_reason:null,next_actor:null,next_review_at:null};
  upstream.mockResolvedValueOnce(Response.json({schema_version:2,auction_id:auctionId,watch_id:watchId,
    actor_id:owner.subjectId,revision:2,amount_minor:null,active:false,standing:null}))
    .mockResolvedValueOnce(Response.json(receipt)).mockResolvedValueOnce(Response.json(receipt));
  const signal=new AbortController().signal;
  await expect(readOwnMaximum(auctionId,owner,signal)).resolves.toHaveProperty('revision',2);
  await expect(sendMaximum(auctionId,intent,signal)).resolves.toEqual(receipt);
  await expect(lookupMaximum(auctionId,intent,signal)).resolves.toEqual(receipt);

  expect(upstream.mock.calls.map(([method,path])=>[method,path])).toEqual(
    Array.from({length:3},()=>['POST','/v1/auctions/'+auctionId+'/maximum']));
  expect(upstream.mock.calls.map(([, , , options])=>JSON.parse(new TextDecoder().decode(options.body)).action))
    .toEqual(['read_v2','submit_v2','lookup_v2']);
  expect(upstream.mock.calls[1][3].headers.get('Idempotency-Key')).toBe(intent.key);
});
