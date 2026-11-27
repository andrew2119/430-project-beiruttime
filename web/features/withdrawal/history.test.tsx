import {beforeEach,expect,it,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider,QueryObserver,useQuery as realUseQuery} from '@tanstack/react-query';
import {LocaleContext} from '@/shell/locale-context';
import Withdrawals from './page';
import en from './en.json';
import ar from './ar.json';

const mock=vi.hoisted(()=>({history:null as unknown,options:null as unknown}));
vi.mock('@tanstack/react-query',async importOriginal=>{
  const original=await importOriginal<typeof import('@tanstack/react-query')>();
  return {...original,useQuery:(options:Parameters<typeof realUseQuery>[0])=>{
    if(options.queryKey[0]==='l13-withdrawals'){
      mock.options=options;
      return mock.history??{isPending:true};
    }
    return {data:{items:[]},isPending:false};
  }};
});
vi.mock('@/features/identity/session',()=>({
  useSession:()=>({access_fingerprint:'owner',principal:{organization_grants:[]}}),
  useSessionState:()=> 'authenticated',authenticatedRequest:vi.fn(),signInHref:vi.fn(),
}));
let client:QueryClient;
beforeEach(()=>{client=new QueryClient({defaultOptions:{queries:{retry:false}}});mock.history=null;});
function render(locale:'en'|'ar'){
  return renderToStaticMarkup(<LocaleContext value={locale}><QueryClientProvider client={client}><Withdrawals/></QueryClientProvider></LocaleContext>);
}
it.each(['en','ar'] as const)('retains rows and their operation on an uncached page transition in %s',locale=>{
  render(locale);
  const options=mock.options as Parameters<typeof realUseQuery>[0];
  const data={items:[{id:'retained-operation',listing_id:'retained-watch',base_revision:2,state:'pending',status:'pending',operation_key:'original-key',reason:'Unavailable'}],page:1,page_size:25,total:50};
  const key=['l13-withdrawals','owner','',1];
  client.setQueryData(key,data);
  const observer=new QueryObserver(client,{...options,queryKey:key,enabled:false});
  observer.setOptions({...options,queryKey:[...key.slice(0,3),2],enabled:false});
  const result=observer.getCurrentResult();
  expect(result.isPending).toBe(false);
  expect(result.isPlaceholderData).toBe(true);
  expect(result.data).toBe(data);
  mock.history={...result,isFetching:true};
  const html=render(locale),t=locale==='ar'?ar:en;
  expect(html).toContain('retained-watch');
  expect(html).toContain(t.loadingHistoryPage);
  expect(html).toContain(`${t.page} 1`);
  expect(html).not.toContain(`${t.page} 2`);
  expect(html).toContain(t.retry);
  expect((result.data as typeof data).items[0].operation_key).toBe('original-key');
  observer.destroy();
});
it.each([['other-owner',''],['owner','other-business']])('clears retained rows across access scope %s %s', (identity,organization)=>{
  render('en');
  const options=mock.options as Parameters<typeof realUseQuery>[0];
  const key=['l13-withdrawals',identity,organization,1];
  client.setQueryData(key,{items:[{listing_id:'private-watch'}]});
  const observer=new QueryObserver(client,{...options,queryKey:key,enabled:false});
  observer.setOptions({...options,queryKey:['l13-withdrawals','owner','',2],enabled:false});
  expect(observer.getCurrentResult().data).toBeUndefined();
  expect(observer.getCurrentResult().isPending).toBe(true);
  observer.destroy();
});
