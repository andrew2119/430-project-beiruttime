import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { InboxContent, type InboxContentProps } from '../../../../web/features/inbox/content';
import en from '../../../../web/features/inbox/en.json';
import ar from '../../../../web/features/inbox/ar.json';
import { inboxRead, noticePreferencesRead } from '../../../../web/features/inbox/reads';
const {request}=vi.hoisted(()=>({request:vi.fn(async()=>({}))}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:request}));

const noop=()=>{};
const base:InboxContentProps={locale:'en',scope:'personal-one',status:'ready',pending:false,failed:false,refreshing:false,hasPrevious:false,onRefresh:noop,onPrevious:noop,onNext:noop,onPreference:noop,onMark:noop,onOpen:noop,onRetry:noop};
const draw=(props:Partial<InboxContentProps>)=>renderToStaticMarkup(<InboxContent {...base} {...props}/>);
describe('canonical inbox presentation',()=>{
  it('binds the shared read key and request to current access and exact cursor',async()=>{
    const signal=new AbortController().signal;
    const notices=inboxRead('personal-scope','next cursor');
    expect(notices.key).toEqual(['inbox','personal-scope','notices','next cursor']);
    expect(notices.warm).toBe('open-only');
    await notices.ask(signal);
    expect(request).toHaveBeenLastCalledWith('/api/web/v1/communications/v1/inbox?cursor=next%20cursor',{signal,accessFingerprint:'personal-scope'});
    await noticePreferencesRead('personal-scope').ask(signal);
    expect(request).toHaveBeenLastCalledWith('/api/web/v1/communications/v1/inbox/preferences',{signal,accessFingerprint:'personal-scope'});
  });
  it('renders recovery and waiting states in both languages',()=>{
    for(const locale of ['en','ar'] as const){
      const copy=locale==='ar'?ar:en;
      expect(draw({locale,status:'loading'})).toContain(copy.loading);
      expect(draw({locale,status:'denied'})).toContain(copy.accessDeniedBody);
      expect(draw({locale,status:'unavailable'})).toContain(copy.unavailableBody);
      expect(draw({locale,pending:true})).toContain(copy.pending);
      expect(draw({locale,failed:true})).toContain(copy.retrySameAction);
      expect(draw({locale,data:{items:[],unread_count:0,total_count:0,next_cursor:null}})).toContain(copy.emptyInboxBody);
    }
  });
  it('uses server totals and a bounded real page without mounting all records',()=>{
    const items=Array.from({length:20},(_,index)=>({id:`notice-${index}`,kind:'outbid' as const,resource_id:'سجل طويل Mixed Latin ⌚ '+String(index),resource_revision:null,event_time:'2026-11-17T10:00:00Z',read_at:null,cleared_at:null,revision:1,required:true,sample:true,destination:'/v1/inbox/destination'}));
    const html=draw({data:{items,unread_count:1,total_count:1000,next_cursor:'next-page'}});
    expect(html).toContain('1,000');expect((html.match(/<article/g)??[]).length).toBe(20);
    expect(html).toContain(en.loadMore);expect(html).toContain(en.markRead);expect(html).toContain(en.clearNotice);
    expect(html).toContain('سجل طويل Mixed Latin ⌚');expect(html).not.toContain('<main');
    const arabic=draw({locale:'ar',data:{items:items.slice(0,1),unread_count:1,total_count:1,next_cursor:null}});
    expect(arabic).toContain(ar.markRead);expect(arabic).toContain(ar.clearNotice);expect(arabic).toContain('dir="ltr"');
  });
  it('keeps retained notices during failed refresh and hides them on denied access',()=>{
    const data={items:[{id:'private-record',kind:'payment_required' as const,resource_id:'private-order',resource_revision:3,event_time:'2026-11-17T10:00:00Z',read_at:null,cleared_at:null,revision:1,required:true,sample:false,destination:null}],unread_count:1,total_count:1,next_cursor:null};
    expect(draw({data,status:'unavailable',refreshing:true})).toContain('private-order');
    expect(draw({data,status:'denied'})).not.toContain('private-order');
    expect(draw({data})).toContain(en.linkUnavailable);
  });
});


describe('unresolved inbox operations',()=>{
  it('retains a lost command across unrelated actions and retries its exact request',async()=>{
    const {InboxRecovery}=await import('../../../../web/features/inbox/recovery');
    const recovery=new InboxRecovery();
    const body={expected_revision:7},key='original-reference';
    const send=vi.fn().mockRejectedValueOnce(new Error('Response unavailable')).mockResolvedValueOnce(undefined);
    const original=()=>send({body,key});
    const unrelated=vi.fn(async()=>{});
    expect(await recovery.run(original)).toBe('uncertain');
    expect(await recovery.run(unrelated)).toBe('blocked');
    expect(unrelated).not.toHaveBeenCalled();
    expect(recovery.current).toBe(original);
    expect(await recovery.run(recovery.current!)).toBe('confirmed');
    expect(send.mock.calls).toEqual([[{body,key}],[{body,key}]]);
    expect(recovery.current).toBeNull();
    expect(await recovery.run(unrelated)).toBe('confirmed');
  });
  it('disables unrelated controls while keeping recovery available',()=>{
    const html=draw({failed:true,hasPrevious:true,preferences:{optional_enabled:true,revision:1},data:{items:[{id:'one',kind:'outbid',resource_id:'watch',resource_revision:1,event_time:'2026-11-17T10:00:00Z',read_at:null,cleared_at:null,revision:1,required:true,sample:false,destination:'/buyer'}],unread_count:1,total_count:1,next_cursor:'next'}});
    for(const label of [en.markRead,en.clearNotice,en.openRecord,en.previousPage,en.loadMore]){
      const button=(html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g)??[]).find(value=>value.includes('>'+label+'</span>'));
      expect(button).toContain('disabled=');
    }
    const retry=(html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g)??[]).find(value=>value.includes('>'+en.retrySameAction+'</span>'));
    expect(retry).toBeDefined();expect(retry).not.toContain('disabled=');
  });
});

 it('mounts the rebuilt composition on the original route',()=>{
   const route=readFileSync(new URL('../../../../web/app/(inbox)/inbox/page.tsx',import.meta.url),'utf8');
   expect(route).toContain("export { default } from '@/features/inbox/page';");
   const entry=readFileSync(new URL('../../../../web/features/inbox/page.tsx',import.meta.url),'utf8');
   expect(entry).toContain("export { CanonicalInboxPage as default } from './canonical';");
 });

 describe('definitive command refusal',()=>{
   it('releases a stale revision and permits a current action',async()=>{
     const {InboxRecovery}=await import('../../../../web/features/inbox/recovery');
     const {ApiError}=await import('../../../../web/lib/api/client');
     for(const status of [400,401,403,404,409,410,422]){
       const recovery=new InboxRecovery();
       const stale=vi.fn(async()=>{throw new ApiError(status,'stale_revision','refusal');});
       expect(await recovery.run(stale)).toBe('refused');
       expect(recovery.current).toBeNull();
       const current=vi.fn(async()=>{});
       expect(await recovery.run(current)).toBe('confirmed');
       expect(current).toHaveBeenCalledOnce();
     }
   });
   it('retains the exact command when service availability is uncertain',async()=>{
     const {InboxRecovery}=await import('../../../../web/features/inbox/recovery');
     const {ApiError}=await import('../../../../web/lib/api/client');
     const recovery=new InboxRecovery();
     const action=vi.fn().mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValueOnce(undefined);
     expect(await recovery.run(action)).toBe('uncertain');
     expect(recovery.current).toBe(action);
     expect(await recovery.run(action)).toBe('confirmed');
   });
   it('provides current-state recovery in both languages without blocking commands',()=>{
     for(const locale of ['en','ar'] as const){
       const copy=locale==='ar'?ar:en;
       const html=draw({locale,refused:true});
       expect(html).toContain(copy.actionRefusedBody);
       expect(html).not.toContain(copy.retrySameAction);
     }
   });
 });
