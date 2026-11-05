import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import { PolicyFacts } from './panel';
import en from './en.json';
import ar from './ar.json';
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));
const binding={auctionId:'11111111-1111-4111-8111-111111111111',listingId:'44444444-4444-4444-8444-444444444444',buyerId:'22222222-2222-4222-8222-222222222222',revision:2,currency:'USD',price:500000};
it.each(['en','ar'] as const)('renders %s public reserve and extension facts without secret economics',locale=>{
 const t=locale==='ar'?ar:en;
 const html=renderToStaticMarkup(createElement(PolicyFacts,{locale,currency:'USD',policy:{auction_id:binding.auctionId,revision:2,end_version:3,current_ends_at:'2026-11-05T15:00:00Z',server_time:'2026-11-05T14:59:00Z',frozen:true,reserve_set:true,reserve_met:false,mode:'prebid_pending',buy_now_minor:500000,extension_policy:'last-two-minutes.v1'}}));
 expect(html).toContain(t.extension);expect(html).toContain(t.boundary);expect(html).toContain(t.held);expect(html).not.toContain(binding.buyerId);expect(html).not.toContain('reserve_minor');
});
it('keeps dictionary keys equal',()=>expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort()));
