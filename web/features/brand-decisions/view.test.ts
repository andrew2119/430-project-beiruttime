import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import type { BrandRequest } from '@contracts/contracts-catalog/request-drafts/v2';
import type { DecisionReadiness } from '@contracts/contracts-catalog/brand-decisions/v1';
import en from './en.json';
import ar from './ar.json';
const state=vi.hoisted(()=>({
  locale:'en',current:{} as Record<string,unknown>,ready:{} as Record<string,unknown>,
  rules:{} as Record<string,unknown>,request:null as BrandRequest|null,
}));
vi.mock('@/features/identity/session',()=>({
  useSession:()=>({access_fingerprint:'sample-brand',principal:{actor:{organization_id:brand},organizations:[brand]}}),
  signInHref:()=>'/en/account',authenticatedRequest:vi.fn(),
}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:'sample-brand',roles:['brand']})}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()}),useSearchParams:()=>new URLSearchParams('organization_id='+brand)}));
vi.mock('./references',()=>({default:()=>createElement('div',null,'Sample private reference')}));
vi.mock('@tanstack/react-query',()=>({
  useInfiniteQuery:()=>({data:{pages:[{items:[state.request]}]},isPending:false,error:null,hasNextPage:false,refetch:vi.fn()}),
  useQuery:({queryKey}:{queryKey:unknown[]})=>({refetch:vi.fn(),isPending:false,isFetching:false,...(
    queryKey[0]==='brand-decision'?state.current:queryKey[0]==='brand-decision-ready'?state.ready:
    queryKey[0]==='compatibility-rules'?state.rules:{data:{items:[{id:brand,public_name:'Sample brand'}]}}
  )}),
}));
import BrandDecisions from './view';
const id=(number:number)=>`00000000-0000-4000-8000-${String(number).padStart(12,'0')}`;
const brand=id(2);
const part=(number:number)=>({option_id:id(number),option_revision:1,definition:{label:{en:'Sample part',ar:'قطعة تجريبية'}}});
const request:BrandRequest={
  id:id(1),draft_id:id(8),revision:1,buyer_id:id(3),brand_id:brand,status:'submitted',configuration_digest:'a'.repeat(64),
  watch_context:'owned_watch',watch_reference:'Sample watch',scope_intent:'Sample private scope',notes:'Sample private notes',
  created_at:'2026-11-05T10:00:00Z',configuration:{
    brand_id:brand,base_model:'Sample base',caliber:'Sample caliber',reference_ids:[id(9)],
    movement_mounting:{case:'Sample case',dial:'Sample dial',hands:'Sample hands',functions:[]},
    selections:{color:part(10),material:part(11),dial:part(12),sophistication:part(13),movement:part(14)},
  },
};
function render(){return renderToStaticMarkup(createElement(BrandDecisions));}
function available():{data:DecisionReadiness}{return {data:{status:'available',execution_authority:false,bindings:{
  watch_id:id(20),request_id:request.id,request_revision:1,brand_id:brand,subject_id:request.buyer_id,approver_id:id(4),
  assessment_id:id(5),assessment_revision:1,quote_id:id(6),quote_revision:1,grant_id:id(7),grant_revision:1,
  amount_minor:515000,currency:'USD',purpose:'brand_approval',consent_revision:1,assignment_revision:1,
}}};}
describe('brand decision availability and private scope',()=>{
  beforeEach(()=>{
    state.locale='en';state.request=request;state.current={data:{status:'not_decided',execution_authority:false}};
    state.ready={data:{status:'unavailable',code:'approval_unavailable',execution_authority:false}};
    state.rules={data:{items:[]}};
  });
  it('does not treat a truthy unavailable read as current approval bindings',()=>{
    const html=render();expect(html).toContain(en.prerequisitesUnavailable);expect(html).not.toContain(en.ready);expect(html).not.toContain('$5,150.00');
  });
  it('shows only an explicitly available bounded amount',()=>{
    state.ready=available();const html=render();expect(html).toContain(en.ready);expect(html).toContain('$5,150.00');
  });
  it('does not reuse cached bindings after a failed recheck',()=>{
    state.ready={...available(),error:new ApiError(503,'unavailable','')};const html=render();expect(html).not.toContain(en.ready);expect(html).not.toContain('$5,150.00');
  });
  it('does not reuse cached bindings while their recheck is running',()=>{
    state.ready={...available(),isFetching:true};expect(render()).not.toContain(en.ready);
  });
  it('removes private scope and reference previews on a known record permission denial',()=>{
    state.current={data:{status:'not_decided'},error:new ApiError(403,'forbidden','')};const html=render();expect(html).toContain(en.denied);expect(html).not.toContain('Sample private scope');expect(html).not.toContain('Sample private notes');expect(html).not.toContain('Sample private reference');
  });
  it('provides honest recovery when current rules could not load',()=>{
    state.rules={error:new ApiError(503,'unavailable','')};expect(render()).toContain(en.ruleError);
  });
  it('renders unavailable prerequisites and rule errors in Arabic',()=>{
    state.locale='ar';state.rules={error:new ApiError(503,'unavailable','')};const html=render();expect(html).toContain(ar.prerequisitesUnavailable);expect(html).toContain(ar.ruleError);
  });
});
