import {beforeEach,expect,it,vi} from 'vitest';
vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn()}));
vi.mock('@/lib/api/client',async original=>({...await original<typeof import('@/lib/api/client')>(),request:vi.fn()}));
import {ApiError,request} from '@/lib/api/client';
import {readAuction,readLots} from './api';
const send=vi.mocked(request);
beforeEach(()=>send.mockReset());
it('reads the versioned canonical mode rather than assuming v1 includes commitment fields',async()=>{
 send.mockResolvedValueOnce({items:[{id:'auction',currency:'USD',mode:'prebid_reserved'}]});
 expect(await readLots('listing')).toMatchObject({items:[{mode:'prebid_reserved'}]});
 expect(send.mock.calls[0][0]).toBe('/api/web/v1/auction/v2/auctions?listing_id=listing');
 expect(send).toHaveBeenCalledTimes(1);
});
it('supports a rolling v1 deployment only when the v2 route is missing',async()=>{
 send.mockRejectedValueOnce(new ApiError(404,'not_found','')).mockResolvedValueOnce({id:'auction',currency:'USD'});
 await readAuction('auction');
 expect(send.mock.calls.map(call=>call[0])).toEqual(['/api/web/v1/auction/v2/auctions/auction','/api/web/v1/auction/v1/auctions/auction']);
});
it('keeps historic non-USD auctions outside active dollar listings',async()=>{
 send.mockResolvedValueOnce({items:[{id:'legacy',currency:'LBP'},{id:'current',currency:'USD'}]});
 expect(await readLots()).toMatchObject({items:[{id:'current'}]});
 send.mockResolvedValueOnce({id:'legacy',currency:'LBP'});
 await expect(readAuction('legacy')).rejects.toMatchObject({code:'legacy_currency_review'});
});
it('does not hide a current-state outage behind an older projection',async()=>{
 send.mockRejectedValueOnce(new ApiError(503,'unavailable',''));
 await expect(readLots()).rejects.toMatchObject({status:503});expect(send).toHaveBeenCalledTimes(1);
});
it('does not restart a cancelled account/resource read through v1',async()=>{
 const controller=new AbortController();controller.abort();send.mockRejectedValueOnce(new ApiError(404,'not_found',''));
 await expect(readLots(undefined,controller.signal)).rejects.toMatchObject({status:404});expect(send).toHaveBeenCalledTimes(1);
});
