import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError } from '../../../../web/lib/api/client';
import { LocaleContext } from '../../../../web/shell/locale-context';
import DeferredSavedPage, { ComposedSavedPage as SavedPage } from '../../../../web/features/saved-watches/page';
import { copy } from '../../../../web/features/saved-watches/copy';
const state = vi.hoisted(()=>({session:true,read:{data:undefined as unknown,error:null as unknown,isPending:false,isError:false,isFetching:false,refetch:vi.fn()}}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session?{access_fingerprint:'current'}:null,useSessionState:()=>state.session?'authenticated':'signed-out',authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>state.read}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:unknown})=>children}));
function render(locale:'en'|'ar') {return renderToStaticMarkup(<LocaleContext value={locale}><SavedPage/></LocaleContext>);}
beforeEach(()=>{state.session=true;Object.assign(state.read,{data:undefined,error:null,isPending:false,isError:false,isFetching:false});});
describe('private saved watch view',()=>{
  it.each(['en','ar'] as const)('labels unavailable records, missing facts and exact dollars in %s',locale=>{
    state.read.data={items:[{watch_id:'watch-1',revision:1,saved:true,alerts:[],status:'unavailable',title:null,price_minor:null},{watch_id:'watch-2',revision:1,saved:true,alerts:['ending'],status:'available',title:'ساعة طويلة / Long watch ⌚ '.repeat(30),price_minor:500001}],total:1000,offset:0,limit:20};
    const html=render(locale);
    expect(html).toContain(copy[locale].unavailable);expect(html).toContain(copy[locale].unnamed);expect(html).toContain(copy[locale].priceMissing);
    expect(html).toContain(locale==='ar'?'٥٬٠٠٠٫٠١ دولار أمريكي':'5,000.01 USD');
    expect((html.match(/<h1\b/g)??[]).length).toBe(1);
    expect(html).toContain(copy[locale].next);expect(html).toContain('Long watch ⌚');
  });
  it.each(['en','ar'] as const)('hides all retained private information after denial in %s',locale=>{
    state.read.data={items:[{title:'private retained title'}],total:987654,offset:0,limit:20};
    state.read.error=new ApiError(403,'denied','');state.read.isError=true;
    const html=render(locale);
    expect(html).toContain(copy[locale].denied);expect(html).not.toContain(copy[locale].total);expect(html).not.toContain('private retained title');
  });
  it.each(['en','ar'] as const)('provides sign-in, loading, empty and retry recovery in %s',locale=>{
    state.session=false;expect(render(locale)).toContain(copy[locale].signIn);
    state.session=true;state.read.isPending=true;expect(render(locale)).toContain('aria-busy="true"');
    state.read.isPending=false;state.read.data={items:[],total:0,offset:0,limit:20};expect(render(locale)).toContain(copy[locale].empty);
    state.read.error=new ApiError(503,'unavailable','');state.read.isError=true;expect(render(locale)).toContain(copy[locale].retry);
  });
});

describe('deferred shared composition',()=>{
  it.each(['en','ar'] as const)('renders recovery without a read scope in %s',locale=>{
    const html=renderToStaticMarkup(<LocaleContext value={locale}><DeferredSavedPage/></LocaleContext>);
    expect(html).toContain(copy[locale].compositionPending);
    expect(html).toContain(copy[locale].account);
    expect(html).not.toContain(copy[locale].reference);
  });
});
