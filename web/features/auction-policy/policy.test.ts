import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import { PolicyFacts } from './panel';
import type { PolicySnapshot } from '@contracts/contracts-auction/policy';
import en from './en.json';
import ar from './ar.json';
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));
const policy:PolicySnapshot={policy_version:'fixed-end.v2',auction_id:'auction',revision:2,end_version:3,current_ends_at:'2026-11-16T15:00:00Z',server_time:'2026-11-16T14:59:00Z',frozen:true,reserve_set:true,mode:'prebid_pending',schedule_state:'ended_legacy_review'};
it.each(['en','ar'] as const)('renders %s fixed end without reserve comparison or removed controls',locale=>{
 const t=locale==='ar'?ar:en;
 const html=renderToStaticMarkup(createElement(PolicyFacts,{locale,policy}));
 expect(html).toContain(t.fixedEnd);expect(html).toContain(t.boundary);expect(html).toContain(t.endedReview);
 expect(html).not.toContain(t.reserveNotMet);expect(html).not.toContain('<input');expect(html).not.toContain('<select');
});
it.each(['en','ar'] as const)('renders the seller-only reserve comparison in %s',locale=>{
 const html=renderToStaticMarkup(createElement(PolicyFacts,{locale,policy:{...policy,reserve_met:false,cancellation_eligible:false}}));
 expect(html).toContain((locale==='ar'?ar:en).reserveNotMet);
});
it('keeps dictionary keys equal',()=>expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort()));
