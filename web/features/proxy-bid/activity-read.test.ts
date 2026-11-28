import {expect,it,vi} from 'vitest';
import {ApiError} from '@/lib/api/client';
import {activityPageBoundary,activityRead,continuesActivity,type ActivityPageBoundary} from './activity-read';

const request=vi.hoisted(()=>vi.fn());
vi.mock('./session',()=>({authenticatedRequest:request}));

const bid=(status:'leading'|'outbid'='leading')=>({
  auction_id:'00000000-0000-4000-8000-000000000001',
  listing_id:'00000000-0000-4000-8000-000000000002',
  status,lifecycle:'live' as const,currency:'USD' as const,revision:1,is_demo:true,current_price_minor:430000,
  starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',
});

it.each(['leading','outbid'] as const)('uses source totals and follows the cursor for %s',async view=>{
  const signal=new AbortController().signal;
  const options={signal,accessFingerprint:'test-access',cache:'no-store'};
  const items=[bid(view)];
  const first={schema_version:2,state:'available',total:1000,next_cursor:'test/opaque+cursor',items};
  const next={...first,next_cursor:'test-page-3',items:[{...items[0],auction_id:items[0].listing_id}]};
  request.mockResolvedValueOnce(first).mockResolvedValueOnce(next);
  const endpoint='/api/web/v1/communications/v1/buyer-workspace';
  await expect(activityRead('test-access',view,null).ask(signal)).resolves.toEqual(first);
  expect(request).toHaveBeenLastCalledWith(endpoint+'?view='+view,options);
  await expect(activityRead('test-access',view,first.next_cursor).ask(signal)).resolves.toEqual(next);
  expect(request).toHaveBeenLastCalledWith(endpoint+'?view='+view+'&cursor=test%2Fopaque%2Bcursor',options);
  for(const status of [403,503]) {
    request.mockRejectedValueOnce(new ApiError(status,'unavailable',''));
    await expect(activityRead('test-access',view,null).ask(signal)).rejects.toMatchObject({status});
    expect(request).toHaveBeenLastCalledWith(endpoint+'?view='+view,options);
  }
});

it('fails closed if the registered route still returns the original workspace envelope',async()=>{
  request.mockResolvedValueOnce({version:1,bids:{items:[]}});
  await expect(activityRead('test-access','leading',null).ask(new AbortController().signal))
    .rejects.toMatchObject({status:503,code:'invalid_activity_page'});
});

it.each([null,false,[],{}, {...bid(),listing_id:{}}, {...bid(),current_price_minor:null},
  {...bid(),revision:true}, {...bid(),state:'won'}, {...bid(),buyer_id:bid().auction_id}, {...bid(),status:'outbid'}, {...bid(),ends_at:'bad'}])(
  'rejects malformed activity %j and allows a corrected response on retry',async row=>{
    const page={schema_version:2,state:'available',total:1,next_cursor:null};
    request.mockResolvedValueOnce({...page,items:[row]}).mockResolvedValueOnce({...page,items:[bid()]});
    const read=activityRead('test-access','leading',null);
    const signal=new AbortController().signal;
    await expect(read.ask(signal)).rejects.toMatchObject({status:503,code:'invalid_activity_page'});
    await expect(read.ask(signal)).resolves.toEqual({...page,items:[bid()]});
  });

it.each(['leading','outbid','calendar','won','lost','no_sale','unpaid','released'] as const)('reads producer absence without substituting data for %s',async view=>{
  const {default:cases}=await import('../../../packages/contracts-comms/buyer-workspace/fixtures/current.v2.json');
  const page=cases.find(item=>item.case==='producer_absent')!.response!;
  const read=activityRead('test-access',view,null);
  const signal=new AbortController().signal;
  request.mockResolvedValueOnce(page);
  await expect(read.ask(signal)).resolves.toEqual(page);
  for(const invalid of [
    {...page,total:0},
    {...page,next_cursor:'unexpected'},
    {...page,items:[bid()]},
    {...page,state:'partial'},
  ]) {
    request.mockResolvedValueOnce(invalid);
    await expect(read.ask(signal)).rejects.toMatchObject({code:'invalid_activity_page'});
  }
});

it('requires 1000 distinct rows before reaching the end of a complete sequence',()=>{
  const trail:ActivityPageBoundary[]=[];
  let cursor:string|null=null;
  const pageAt=(offset:number)=>({
    schema_version:2 as const,state:'available' as const,total:1000,
    next_cursor:offset===950?null:`test-page-${offset+50}`,
    items:Array.from({length:50},(_,index)=>({...bid(),auction_id:
      `00000000-0000-4000-8000-${String(offset+index).padStart(12,'0')}`})),
  });
  for(let offset=0;offset<1000;offset+=50) {
    const page=pageAt(offset);
    expect(continuesActivity(trail,page)).toBe(true);
    if(offset===50) {
      expect(continuesActivity(trail,{...page,next_cursor:null})).toBe(false);
      expect(continuesActivity(trail,{...page,items:pageAt(0).items})).toBe(false);
      expect(continuesActivity(trail,{...page,total:1001})).toBe(false);
    }
    if(offset===100) expect(continuesActivity(trail,{...page,next_cursor:'test-page-50'})).toBe(false);
    trail.push(activityPageBoundary(cursor,page));
    cursor=page.next_cursor;
  }
  expect(cursor).toBeNull();
});
