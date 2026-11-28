import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PageReadProvider, usePageReadScope } from '@/lib/page-speed/provider';
import { listingAuctionRead } from '@/features/proxy-bid/listing-auction-read';
import { expect, it, vi } from 'vitest';
import BidSlot from './bid-slot';
import type { Auction } from './api';
import en from './en.json';
import ar from './ar.json';
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'sample-buyer',principal:{actor:{subject_id:'sample-buyer'}}}),useSessionState:()=> 'authenticated',authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:()=>'/en/account'}));
const lot:Auction={id:'sample-auction',listing_id:'sample-listing',currency:'USD',opening_minor:400000,current_minor:0,next_minimum_minor:400000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2026-11-05T10:00:00Z',ends_at:'2026-11-05T11:00:00Z',server_time:'2026-11-05T10:30:00Z',revision:2,accepted_sequence:0,rules_version:'ordinary.v1',extension_policy:'last-two-minutes.v1',high_value_minor:1000000,reserve_set:true,leader:null,status:'live'};
function render(mode:Auction['mode'],locale:'en'|'ar'){
 function Snapshot() {
  const scope=usePageReadScope();
  scope.client.setQueryData(['bt-page',scope.key,...listingAuctionRead(lot.listing_id).key],{items:[{...lot,mode}]});
  scope.client.setQueryData(['bt-page',scope.key,'auction-bid-slot-history',lot.id,lot.revision],{items:[]});
  return createElement(BidSlot,{resourceId:lot.listing_id,locale});
 }
 return renderToStaticMarkup(createElement(PageReadProvider,{children:createElement(Snapshot)}));
}
it.each(['listing_edit_pending','first_bid_pending','prebid_pending','prebid_reserved','closed_no_sale','closed_winner'] as const)('removes bid controls in canonical mode %s',mode=>{for(const locale of ['en','ar'] as const){const html=render(mode,locale),t=locale==='ar'?ar:en;expect(html).toContain(t.saleHeld);expect(html).toContain(t.heldStatus);expect(html).not.toContain('<form');}});
it.each([undefined,'bidding'] as const)('preserves v1 and active v2 bidding controls for mode %s',mode=>{expect(render(mode,'en')).toContain('<form');});
