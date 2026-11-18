import {beforeEach,expect,it,vi} from 'vitest';
import {interpretBeirut, scheduleContract} from './fixtures/schedule-contract';
const state={origin:true,forward:vi.fn()};
const POST=scheduleContract({origin:()=>state.origin,forward:(request,context)=>state.forward(request,context)});
beforeEach(()=>{state.origin=true;state.forward.mockReset();state.forward.mockResolvedValue(Response.json({status:'succeeded'}));});
const body={listing_id:'listing',currency:'USD',opening_minor:400000,reserve_minor:450000,increment_bands:[{from_minor:0,step_minor:10000}],starts_local:'2026-11-16T19:00',ends_local:'2026-11-17T19:00'};
function request(input:unknown,authorization=true){return new Request('http://localhost/api/web/v2/auction-schedules?organization_id=business',{method:'POST',headers:{'Content-Type':'application/json','Origin':'http://localhost','Idempotency-Key':'stable',...(authorization?{'Authorization':'Bearer current'}:{})},body:JSON.stringify(input)});}
it.each([['2026-11-16T12:00','2026-11-16T10:00:00.000Z','+02:00'],['2026-06-16T12:00','2026-06-16T09:00:00.000Z','+03:00']])('matches the frozen civil-time example %s',(local,utc,offset)=>expect(interpretBeirut(local)).toMatchObject({local,utc,offset,time_zone:'Asia/Beirut'}));
it.each(['2026-03-29T00:30','2026-02-30T12:00','2026-11-16T24:00','2026-11-16T12:00Z'])('requires correction for missing/invalid civil time %s',local=>expect(()=>interpretBeirut(local)).toThrow('invalid_beirut_time'));
it('requires correction rather than assuming an offset during the repeated hour',()=>expect(()=>interpretBeirut('2026-10-24T23:30')).toThrow('ambiguous_beirut_time'));
it('reviews local times and offsets without scheduling or allocating',async()=>{
 const response=await POST(request({...body,review_only:true}));expect(response.status).toBe(200);expect(response.headers.get('Cache-Control')).toBe('no-store');
 expect(await response.json()).toMatchObject({starts:{local:body.starts_local,utc:'2026-11-16T17:00:00.000Z',offset:'+02:00'}});expect(state.forward).not.toHaveBeenCalled();
});
it('requires confirmation of the exact interpreted time before scheduling',async()=>{
 const response=await POST(request({...body,confirmed_starts_at:'wrong',confirmed_ends_at:'wrong'}));expect(response.status).toBe(422);expect(state.forward).not.toHaveBeenCalled();
});
it('the local contract forwards converted instants with the same scope and key',async()=>{
 const response=await POST(request({...body,confirmed_starts_at:interpretBeirut(body.starts_local).utc,confirmed_ends_at:interpretBeirut(body.ends_local).utc}));expect(response.status).toBe(200);
 const [forwarded,context]=state.forward.mock.calls[0] as [Request,{params:Promise<unknown>}];
 expect(await forwarded.json()).toEqual({listing_id:'listing',currency:'USD',opening_minor:400000,reserve_minor:450000,increment_bands:body.increment_bands,starts_at:'2026-11-16T17:00:00.000Z',ends_at:'2026-11-17T17:00:00.000Z'});
 expect(new URL(forwarded.url).search).toBe('?organization_id=business');expect(forwarded.headers.get('Idempotency-Key')).toBe('stable');expect(forwarded.headers.get('Authorization')).toBe('Bearer current');expect(await context.params).toEqual({service:'auction',path:['v1','auctions']});
});
it.each([{extension_policy:'last-two-minutes.v1'},{buy_now_minor:500000},{currency:'LBP'},{ends_local:'2026-11-16T18:00'}])('refuses removed settings, non-USD and invalid schedules %j',async change=>{
 expect((await POST(request({...body,...change}))).status).toBe(422);expect(state.forward).not.toHaveBeenCalled();
});
it('retains origin, sign-in and bounded-body checks',async()=>{
 state.origin=false;expect((await POST(request(body))).status).toBe(403);state.origin=true;
 expect((await POST(request(body,false))).status).toBe(401);
 expect((await POST(request({padding:'x'.repeat(65537)}))).status).toBe(413);expect(state.forward).not.toHaveBeenCalled();
});
