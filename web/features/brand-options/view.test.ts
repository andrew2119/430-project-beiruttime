import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Configuration } from '@contracts/contracts-catalog/options';
import type { Session } from '@contracts/contracts-identity/accounts';
const state=vi.hoisted(()=>({
  session:null as Session|null,
  status:'signed-out',
  data:{} as Record<string,unknown>,
  reads:vi.fn(),refresh:vi.fn(),
}));
vi.mock('@/features/identity/session',()=>({
  useSession:()=>state.session,useSessionState:()=>state.status,
  refreshSession:state.refresh,signInHref:()=>'/en/account?next=%2Fcustomize',
}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/registry-loader',()=>({hasRoute:()=>false}));
vi.mock('@/features/movement-option/view',()=>({default:({brandId}:{brandId:string})=>createElement('section',{'data-movement-brand':brandId})}));
vi.mock('./configuration-review',()=>({default:({id,revision}:{id:string;revision:number})=>createElement('section',{'data-configuration':id,'data-configuration-revision':revision})}));
vi.mock('@tanstack/react-query',()=>({
  useQueryClient:()=>({setQueryData:vi.fn(),invalidateQueries:vi.fn()}),
  useInfiniteQuery:()=>({data:{pages:[{items:[]}]},isSuccess:true,hasNextPage:false}),
  useQuery:({queryKey}:{queryKey:unknown[]})=>{
    state.reads(queryKey);
    return {data:state.data[String(queryKey[1])],error:null,isLoading:false};
  },
}));
import BrandOptions, { OptionDetails } from './view';
import ar from './ar.json';
import en from './en.json';

const definition={component:'case' as const,label:{en:'Sample midnight',ar:'نموذج ليلي'},
  base_models:['atelier-38'],calibers:['manual-01'],available:true,
  details:{color:{en:'Blue',ar:'أزرق'},finish:{en:'Brushed',ar:'مصقول'},coating:null,swatch:'#204060'}};
const saved:Configuration={
  id:'50000000-0000-4000-8000-000000000001',brand_id:'20000000-0000-4000-8000-000000000001',
  base_model:'atelier-38',caliber:'manual-01',revision:5,state:'saved_not_submitted',feasibility:'not_assessed',
  reference_ids:[],updated_at:'2026-11-04T10:00:00Z',
  selections:[{kind:'color',component:'case',option_id:'60000000-0000-4000-8000-000000000001',
    option_revision:2,reference_ids:[],definition,current:true}],
};
function render(initial:Parameters<typeof BrandOptions>[0]={}) {
  return renderToStaticMarkup(createElement(BrandOptions,initial));
}
function signIn() {
  state.status='authenticated';
  state.session={access_fingerprint:'current-buyer',access_token:'synthetic-test-token'} as Session;
}
describe('canonical option view state without effect mirrors',()=>{
  beforeEach(()=>{
    state.session=null;state.status='signed-out';state.data={};state.reads.mockClear();state.refresh.mockClear();
    state.data.catalog={brand:{organization_id:saved.brand_id,name:{en:'Sample Atelier',ar:'مشغل نموذجي'},sample:true},
      items:[{...definition,kind:'color',id:saved.selections[0].option_id,revision:2}]};
  });
  it('derives restoration directly from the SDK without another restoration flight',()=>{
    state.status='restoring';
    const html=render();
    expect(html).toContain(en.loadingSaved);expect(html).not.toContain(en.signInBody);
    expect(state.refresh).not.toHaveBeenCalled();
  });
  it('derives unavailable and retry state without rendering a false signed-out result',()=>{
    state.status='unavailable';
    const html=render();
    expect(html).toContain(en.identityUnavailable);expect(html).toContain(en.retry);
    expect(html).not.toContain(en.signInBody);
  });
  it('shows the sign-in link only after the SDK acknowledges signed-out state',()=>{
    expect(render()).toContain('/en/account?next=%2Fcustomize');
    expect(render()).toContain(en.signInBody);
  });
  it('renders an acknowledged private snapshot immediately without waiting for an effect',()=>{
    signIn();state.data.configuration=saved;
    const html=render({initialConfiguration:saved.id});
    expect(html).toContain(en.savedRevision);expect(html).toContain('Sample midnight');
    expect(html).not.toContain(en.summaryEmpty);
    expect(html).toContain('atelier-38');expect(html).toContain('manual-01');
    expect(html).toContain(`data-movement-brand="${saved.brand_id}"`);
    expect(html).toContain(`data-configuration="${saved.id}"`);
    expect(html).toContain('data-configuration-revision="5"');
  });
  it('uses canonical brand bindings rather than stale URL conveniences for catalog reads',()=>{
    signIn();state.data.configuration=saved;
    render({initialConfiguration:saved.id,initialBrand:'stale-brand',initialBase:'stale-base',initialCaliber:'stale-caliber'});
    expect(state.reads).toHaveBeenCalledWith(['brand-options','catalog',saved.brand_id]);
    expect(state.reads).not.toHaveBeenCalledWith(['brand-options','catalog','stale-brand']);
  });
  it('does not expose a cached snapshot when the SDK has no current private owner',()=>{
    state.data.configuration=saved;
    const html=render({initialConfiguration:saved.id});
    expect(html).toContain(en.summaryEmpty);expect(html).not.toContain(en.savedRevision);
  });
  it('retains unsaved URL bindings when no canonical snapshot exists',()=>{
    signIn();
    const html=render({initialBrand:saved.brand_id,initialBase:saved.base_model,initialCaliber:saved.caliber});
    expect(html).toContain('Sample midnight');expect(html).toContain(en.summaryEmpty);
    expect(state.reads).toHaveBeenCalledWith(['brand-options','catalog',saved.brand_id]);
  });
});

 describe('indicative package amounts',()=>{
  const details={interventions:[],exclusions:[],required_tests:[],price_reference:'Synthetic reference',price_minor:12345,currency:'USD' as const,conversion:'none' as const};
  it.each(['en','ar'] as const)('displays cents as dollars in %s',locale=>{
    const html=renderToStaticMarkup(createElement(OptionDetails,{option:{...definition,id:'package',revision:1,kind:'sophistication',component:'package',details},locale,t:locale==='ar'?ar:en}));
    const expected=new Intl.NumberFormat(locale==='ar'?'ar-LB':'en-US',{style:'currency',currency:'USD'}).format(123.45);
    expect(html).toContain(expected);
  });
  it('keeps legacy or invalid amounts unavailable',()=>{
    for(const change of [{currency:'LBP' as const},{price_minor:1.5},{price_minor:-1}]){
      const html=renderToStaticMarkup(createElement(OptionDetails,{option:{...definition,id:'package',revision:1,kind:'sophistication',component:'package',details:{...details,...change}},locale:'en',t:en}));
      expect(html).toContain(en.unavailable);expect(html).not.toContain('<strong>');
    }
  });
 });
