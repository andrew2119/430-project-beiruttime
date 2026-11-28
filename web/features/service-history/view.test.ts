import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
const state=vi.hoisted(()=>({locale:'en',fingerprint:'current',result:{isPending:false,isError:false,data:undefined as unknown,error:null}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:state.fingerprint})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>state.result}));
vi.mock('@/shell/foundation/page',()=>({PageHeader:({title}:{title:string})=>createElement('h1',null,title),PageFrame:({children}:{children:unknown})=>createElement('div',null,children as never)}));
import History from './view';
import en from './en.json';
import ar from './ar.json';
import { validSelection } from './read';

describe('history view',()=>{
  it('has complete translations and preserves work meaning',()=>{
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    for(const locale of ['en','ar']) {
      state.locale=locale;
      const html=renderToStaticMarkup(createElement(History));
      expect(html).toContain(locale==='en'?en.title:ar.title);
    }
  });
  it('renders the primary action as a native form submit in both languages',()=>{
    for(const locale of ['en','ar']) {
      state.locale=locale;
      const html=renderToStaticMarkup(createElement(History));
      const form=html.match(/<form\b[^>]*>([\s\S]*?)<\/form>/)?.[1];
      expect(form).toBeDefined();
      const buttons=form?.match(/<button\b[^>]*>[\s\S]*?<\/button>/g);
      expect(buttons).toHaveLength(1);
      expect(buttons?.[0]).toContain('type="submit"');
      expect(buttons?.[0]).toContain(locale==='en'?en.open:ar.open);
      expect(buttons?.[0]).not.toContain('disabled');
    }
    state.locale='en';
  });
  it('denies signed-out private reads',()=>{
    state.fingerprint='';state.locale='en';
    expect(renderToStaticMarkup(createElement(History))).toContain(en.denied);
    state.fingerprint='current';
  });
  it('hides retained data after a failed read',()=>{
    state.result={isPending:false,isError:true,data:{state:'ready',total:1,items:[{job_id:'PRIVATE'}]},error:null};
    const html=renderToStaticMarkup(createElement(History));
    expect(html).not.toContain('PRIVATE');expect(html).toContain(en.unavailable);
    expect(html).toContain('href="/en/inbox"');
    state.locale='ar';
    const arabic=renderToStaticMarkup(createElement(History));
    expect(arabic).toContain('href="/ar/inbox"');
    expect(arabic).toContain(ar.support);
    state.locale='en';
    state.result={isPending:false,isError:false,data:undefined,error:null};
  });
  it('validates identifiers and bounded whole revisions',()=>{
    expect(validSelection('00000000-0000-0000-0000-000000000003','2')).toBe(true);
    for(const value of ['-1','2.1','1e2','1000000000',''])expect(validSelection('00000000-0000-0000-0000-000000000003',value)).toBe(false);
  });
});

import { historyReducer, initialHistoryState } from './model';
it('retains the same draft, choices, page and pending reference on language change',()=>{
  const draft=historyReducer(initialHistoryState,{type:'patch',patch:{
    watch:'ساعة Watch 👨‍👩‍👧‍👦',revision:'123',selected:['job-one','job-two'],
    selection:{watch:'exact-watch',revision:123,page:49,operation:'read-reference'},
    publication:{state:'pending',operation_id:'exact-publication-reference'},
  }});
  const changed=historyReducer(draft,{type:'language'});
  expect(changed).toBe(draft);
  expect(historyReducer(changed,{type:'language'})).toBe(draft);
  expect(changed.selection?.page).toBe(49);
  expect(changed.publication?.operation_id).toBe('exact-publication-reference');
});
