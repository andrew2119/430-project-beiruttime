import {beforeEach,expect,it,vi} from 'vitest';
const call=vi.hoisted(()=>vi.fn());
vi.mock('@/features/identity/session',()=>({authenticatedRequest:call}));
import {readSellerPolicy,readLegacyOperation} from './api';
beforeEach(()=>call.mockReset());
it('reads current private policy with current identity and business scope',async()=>{
 call.mockResolvedValueOnce({});
 await readSellerPolicy('auction','seller-session',undefined,'selected-business');
 expect(call.mock.calls[0][0]).toContain('/v2/seller/auctions/auction/policy?organization_id=selected-business');
 expect(call.mock.calls[0][1]).toMatchObject({accessFingerprint:'seller-session'});
 expect(call.mock.calls[0][1].method).toBeUndefined();
});
it('reads only the current buyer historical operation and never posts',async()=>{
 call.mockResolvedValueOnce({operation:null});
 await readLegacyOperation('auction','buyer-session');
 expect(call.mock.calls[0][0]).toContain('/v1/auctions/auction/my-prebid');
 expect(call.mock.calls[0][1]).toMatchObject({accessFingerprint:'buyer-session'});
 expect(call.mock.calls[0][1].method).toBeUndefined();
});
