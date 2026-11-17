import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { LocaleContext } from '../../../../web/shell/locale-context';
import { Comparison } from '../../../../web/features/discovery/compare';
import SellerView from '../../../../web/features/discovery/seller-view';
import { SimilarWatches } from '../../../../web/features/discovery/similar';
import { WatchHistory } from '../../../../web/features/discovery/history';
import en from '../../../../web/features/discovery/en.json';
import ar from '../../../../web/features/discovery/ar.json';
import type { WatchDetail } from '../../../../packages/contracts-catalog/discovery';

const state=vi.hoisted(()=>({demo:true,empty:false,cursor:'',error:false}));
vi.mock('react',async importOriginal=>({
  ...await importOriginal<typeof import('react')>(),
  useState:()=>[state.cursor,vi.fn()],
}));
vi.mock('@tanstack/react-query',()=>({
  useQueries:()=>[{data:watch(),isPending:false,isError:false}],
  useQuery:({queryKey}:{queryKey:unknown[]})=>({data:queryKey[2]==='watch'?watch():{items:state.empty?[]:[watch()],next_cursor:null},isPending:false,isError:queryKey[2]==='seller'&&state.error}),
}));
function watch(): WatchDetail {
  return {id:'watch',revision:3,title:'Sample ⌚ ساعة',brand:'Sample',model:'Model',location:'Beirut',sale_mode:'fixed',sale_state:'available',price:{amount:'5000.00',currency:'USD'},thumbnail:null,published_at:'2026-01-01T00:00:00Z',ends_at:null,demo:state.demo,description:'',condition:'Declared',included_items:[],modified:false,modified_parts:[],photos:[],seller:{id:'seller',display_name:'Seller',kind:'private',completed_sales:0,joined_at:null},assurance:{kind:'private_inspection',status:'unavailable'},history:[{occurred_at:'2026-01-01T00:00:00Z',summary_en:'Released record',summary_ar:'سجل مكتمل',user_note:'ملاحظة Watch ⌚'}],history_revision:1,history_next_cursor:'next'};
}
describe('public disclosures and history controls',()=>{
  for(const locale of ['en','ar'] as const) {
    it(`labels every demonstration result in ${locale}`,()=>{
      const t=locale==='ar'?ar:en;
      state.demo=true;state.empty=false;
      const views=[createElement(Comparison,{ids:['watch'],remove:()=>{}}),createElement(SellerView,{id:'watch'}),createElement(SimilarWatches,{id:'other',brand:'Sample'})];
      for(const view of views)expect(renderToStaticMarkup(createElement(LocaleContext,{value:locale},view))).toContain(t.demo);
      state.demo=false;
      for(const view of views)expect(renderToStaticMarkup(createElement(LocaleContext,{value:locale},view))).not.toContain(t.demo);
    });
    it(`labels seller facts with no available listings in ${locale}`,()=>{
      state.demo=true;state.empty=true;
      const html=renderToStaticMarkup(createElement(LocaleContext,{value:locale},createElement(SellerView,{id:'watch'})));
      expect(html).toContain((locale==='ar'?ar:en).demo);
      state.empty=false;
    });
    for(const result of ['error','empty'] as const) {
      it(`offers the first seller page after a continuation becomes ${result} in ${locale}`,()=>{
        const t=locale==='ar'?ar:en;
        state.cursor='expired-page';state.error=result==='error';state.empty=result==='empty';
        try {
          const html=renderToStaticMarkup(createElement(LocaleContext,{value:locale},createElement(SellerView,{id:'watch'})));
          expect(html).toContain(t.first);
          expect(html).toContain(result==='error'?t.retry:t.empty);
          expect(html).not.toContain(t.next);
          state.cursor='';
          const first=renderToStaticMarkup(createElement(LocaleContext,{value:locale},createElement(SellerView,{id:'watch'})));
          expect(first).not.toContain(t.first);
        } finally {
          state.cursor='';state.error=false;state.empty=false;
        }
      });
    }
    it(`links similar results to the complete filtered search in ${locale}`,()=>{
      const html=renderToStaticMarkup(createElement(LocaleContext,{value:locale},createElement(SimilarWatches,{id:'other',brand:'Sample'})));
      expect(html).toContain(`/${locale}/search?brand=Sample`);
      expect(html).toContain((locale==='ar'?ar:en).allSimilar);
    });
    it(`offers continuation and renders actual history in ${locale}`,()=>{
      const html=renderToStaticMarkup(createElement(LocaleContext,{value:locale},createElement(WatchHistory,{watch:watch()})));
      expect(html).toContain(locale==='ar'?'سجل مكتمل':'Released record');
      expect(html).not.toContain(locale==='ar'?'Released record':'سجل مكتمل');
      expect(html).toContain('ملاحظة Watch ⌚');
      expect(html).toContain((locale==='ar'?ar:en).next);
    });
  }
});
