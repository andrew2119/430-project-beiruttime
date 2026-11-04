import {beforeEach,describe,it,expect,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import ProxyBidSlot,{MaximumForm} from './proxy-bid';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
const session=vi.hoisted(()=>({state:'authenticated' as 'restoring'|'unavailable'|'signed-out'|'authenticated',signedIn:true,organizationId:null as string|null,fingerprint:'buyer-A',subjectId:'00000000-0000-0000-0000-000000000001',roles:['buyer']}));
vi.mock('./session',()=>({useBuyerSession:()=>session,authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
beforeEach(()=>{session.state='authenticated';session.signedIn=true;session.organizationId=null;session.roles=['buyer'];});
const lot:AuctionSnapshot={id:'00000000-0000-0000-0000-000000000006',listing_id:'00000000-0000-0000-0000-000000000007',currency:'USD',opening_minor:400000,current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2020-01-01T00:00:00Z',ends_at:'2050-01-01T00:00:00Z',server_time:'2026-01-01T00:00:00Z',revision:4,accepted_sequence:1,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:'bidder-1',status:'live'};
function slot(data:unknown) {
  const client=new QueryClient();client.setQueryData(['listing-auction',lot.listing_id],data);
  return renderToStaticMarkup(<QueryClientProvider client={client}><ProxyBidSlot locale="en" resourceId={lot.listing_id}/></QueryClientProvider>);
}
describe('canonical listing auction slot',()=>{
  it('composes a real quote control only for a canonical live lot',()=>{
    const html=slot({items:[lot]});expect(html).toContain('Review maximum and fees');expect(html).toContain('<input');
  });
  it.each(['scheduled','ended'] as const)('does not permit bids on %s auctions',status=>{
    const html=slot({items:[{...lot,status}]});expect(html).not.toContain('<input');
    expect(html).toContain(status==='ended'?'This auction has ended':'Bidding has not opened');
    expect(html).not.toContain('You won');
  });
  it.each([{id:'not-an-auction'},{listing_id:'another-listing'},{revision:0},{revision:1.5},{currency:'EUR'}])('does not offer a quote for malformed or mismatched canonical identity %j',change=>{
    const html=slot({items:[{...lot,...change}]});expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('<input');
  });
  it('does not turn a malformed public page into empty-success bidding',()=>{
    const html=slot({unexpected:[]});expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('<input');
  });
});
describe('maximum form capability boundary',()=>{
  it.each(['restoring','unavailable'] as const)('cannot submit while the current identity is %s',state=>{
    session.state=state;
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).not.toContain('<input');expect(html).not.toContain('type="submit"');
    expect(html).toContain(state==='restoring'?'Loading':'Temporarily unavailable');
  });
  it('requires individual context even if a represented session has the buyer role',()=>{
    session.organizationId='business-A';
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Your current account cannot use buyer actions.');expect(html).not.toContain('<input');
  });
  it('renders permission denial rather than a fabricated buyer or submit control',()=>{
    session.roles=['operator'];
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Your current account cannot use buyer actions.');expect(html).not.toContain('<input');
  });
  it('preserves the non-secret intended auction route when signing in',()=>{
    session.state='signed-out';session.signedIn=false;
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} signInNext="/buyer/auctions/watch-A" getQuote={vi.fn()}/>);
    expect(html).toContain('/en/account?next=%2Fbuyer%2Fauctions%2Fwatch-A');expect(html).not.toContain('<input');
  });
  it('never enables submission without the current bound pricing capability',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}}/>);
    expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('<input');expect(html).not.toContain('type="submit"');
  });
  it('requires review before confirmation and keeps secret inputs unpersisted',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Review maximum and fees');expect(html).toContain('inputMode="decimal"');
    expect(html).toContain('autoComplete="off"');expect(html).not.toContain('buyer-A');
    expect(html).not.toContain('Set private maximum</button>');
  });
  it('uses Arabic copy and isolated currency without a second form implementation',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="LBP" locale="ar" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('مراجعة الحد الأقصى والرسوم');expect(html).toContain('<bdi dir="ltr">LBP</bdi>');
  });
});
