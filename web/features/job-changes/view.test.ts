import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import en from './en.json';
import ar from './ar.json';
import fixture from '../../../packages/contracts-catalog/job-changes/fixtures.json';
const state=vi.hoisted(()=>({locale:'en',fingerprint:'private-1' as string|null,params:'operation_id=change-1&organization_id=brand-1',query:{} as Record<string,unknown>}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:state.fingerprint})}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn()}));
vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams(state.params)}));
vi.mock('@tanstack/react-query',()=>({useQuery:()=>({refetch:vi.fn(),...state.query})}));
import JobChanges from './view';
const operation=fixture.responses.lost_hold_response;
const render=()=>renderToStaticMarkup(createElement(JobChanges));
describe('private change recovery',()=>{
 beforeEach(()=>{state.locale='en';state.fingerprint='private-1';state.params='operation_id=change-1&organization_id=brand-1';state.query={data:operation};});
 it('shows honest pending state and stable reference',()=>{expect(render()).toContain(en.pending_hold);expect(render()).toContain('change-1');});
 it('renders the same operation in Arabic',()=>{state.locale='ar';expect(render()).toContain(ar.pending_hold);expect(render()).toContain('change-1');});
 it('hides retained private details after denial',()=>{state.query={data:operation,error:new ApiError(403,'denied','')};expect(render()).toContain(en.denied);expect(render()).not.toContain('change-1');});
 it('hides a response for another organization',()=>{state.query={data:{...operation,organization_id:'brand-2'}};expect(render()).toContain(en.unavailable);expect(render()).not.toContain('change-1');});
 it('clears private content on identity loss',()=>{state.fingerprint=null;expect(render()).toContain(en.empty);expect(render()).not.toContain('change-1');});
 it('does not turn an unknown state into success',()=>{state.query={data:{...operation,state:'paid'}};expect(render()).toContain(en.unavailable);});
 it('shows first-load and unavailable recovery',()=>{state.query={isPending:true};expect(render()).toContain(en.loading);state.query={error:new ApiError(503,'unavailable','')};expect(render()).toContain(en.unavailable);});
 it('recovers from missing or malformed operation fields in both languages',()=>{
  for(const locale of ['en','ar']){
   state.locale=locale;
   const text=locale==='ar'?ar:en;
   for(const key of Object.keys(operation)){
    const incomplete:Record<string,unknown>={...operation};delete incomplete[key];
    if(['responsible_operator_id','escalation_at'].includes(key))continue;
    state.query={data:incomplete};
    expect(render()).toContain(text.unavailable);
    expect(render()).not.toContain('change-1');
   }
   for(const update of [{revision:null},{revision:'1'},{revision:0},{revision:1.5},{revision:Infinity},{expected_revision:true},{next_review_at:'invalid'},{execution_authority:true},{invalidated:[]},{state:'title'},{state:'retry'},{state:'__proto__'}]){
    state.query={data:{...operation,...update}};
    expect(render()).toContain(text.unavailable);
    expect(render()).not.toContain('change-1');
   }
  }
 });
 it('keeps complete bilingual text keys' ,()=>{expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());});
});
