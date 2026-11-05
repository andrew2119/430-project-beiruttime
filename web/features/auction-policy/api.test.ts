import {beforeEach,expect,it,vi} from 'vitest';
const call=vi.hoisted(()=>vi.fn());
vi.mock('@/features/identity/session',()=>({authenticatedRequest:call}));
import {ApiError} from '@/lib/api/client';
import {prebid,savePolicy} from './api';
beforeEach(()=>call.mockReset());
const body={expected_revision:7,quote_id:'reviewed-quote'};
it('recovers a lost response through the same actor-owned operation without a second reservation',async()=>{
 const receipt={status:'succeeded',order_id:'retained-order'};
 call.mockRejectedValueOnce(new TypeError('Lost HTTP response')).mockResolvedValueOnce(receipt);
 expect(await prebid('auction',body,'stable-key','current-session')).toBe(receipt);
 expect(call.mock.calls[0][0]).toContain('/auctions/auction/prebid-buy-now');
 expect(call.mock.calls[0][1]).toMatchObject({method:'POST',accessFingerprint:'current-session',headers:{'Idempotency-Key':'stable-key'},body:JSON.stringify(body)});
 expect(call.mock.calls[1][0]).toContain('/prebid-operations/stable-key');
 expect(call.mock.calls[1][1]).toMatchObject({accessFingerprint:'current-session'});
 expect(call).toHaveBeenCalledTimes(2);
});
it('keeps the original unknown result when lookup is unavailable',async()=>{
 const lost=new TypeError('Lost HTTP response');call.mockRejectedValueOnce(lost).mockRejectedValueOnce(new Error('Unavailable'));
 await expect(prebid('auction',body,'same-key','current-session')).rejects.toBe(lost);
 expect(call).toHaveBeenCalledTimes(2);
});
it('does not conceal a known admission denial behind a retry',async()=>{
 const denied=new ApiError(409,'first_bid_exists','');call.mockRejectedValueOnce(denied);
 await expect(prebid('auction',body,'same-key','current-session')).rejects.toBe(denied);expect(call).toHaveBeenCalledTimes(1);
});
it('binds a seller policy edit to the captured revision, operation and organization',async()=>{
 call.mockResolvedValueOnce({status:'succeeded'});
 await savePolicy('auction',{extension_policy:'none.v1',buy_now_minor:null},7,'edit-key','seller-session',undefined,'selected-business');
 expect(call.mock.calls[0][0]).toContain('/policy?organization_id=selected-business');
 expect(call.mock.calls[0][1]).toMatchObject({method:'PATCH',accessFingerprint:'seller-session',headers:{'If-Match':'7','Idempotency-Key':'edit-key'}});
});
