import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import SearchView from '../../../../web/features/discovery/search-view';

const harness=vi.hoisted(()=>({
  params:new URLSearchParams(),pathname:'/en/search',position:0,values:[] as unknown[],
  inputs:{} as Record<string,{value:string;onChange:(event:{target:{value:string}})=>void}>,
  links:{} as Record<string,string>,
}));
vi.mock('react',async original=>({...await original<typeof import('react')>(),
  useState:(initial:unknown)=>{
    const index=harness.position++;
    if(!(index in harness.values))harness.values[index]=typeof initial==='function'?initial():initial;
    return [harness.values[index],(next:unknown)=>{harness.values[index]=typeof next==='function'?next(harness.values[index]):next;}];
  },
}));
vi.mock('../../../../web/node_modules/next/navigation',()=>({useSearchParams:()=>harness.params,usePathname:()=>harness.pathname,useRouter:()=>({push:(href:string)=>{harness.params=new URL(href,'https://example.test').searchParams;}})}));
vi.mock('@tanstack/react-query',()=>({useQueryClient:()=>({prefetchQuery:vi.fn()}),useQuery:()=>({data:{items:[],next_cursor:null},isPending:false,isError:false})}));
vi.mock('../../../../web/registry-loader',()=>({hasRoute:()=>false}));
vi.mock('../../../../web/features/discovery/compare',()=>({Comparison:()=>null,toggleComparison:vi.fn()}));
vi.mock('../../../../web/features/discovery/photo',()=>({PublicPhoto:()=>null}));
vi.mock('../../../../web/shell/page-header',()=>({
  PageLayout:({children}:{children:ReactNode})=>children,
  PageHeader:({tools}:{tools:ReactNode})=>tools,
}));
vi.mock('../../../../web/node_modules/@beirut-time/ui',()=>({
  Input:(props:{name:string;value:string;onChange:(event:{target:{value:string}})=>void})=>{harness.inputs[props.name]=props;return null;},
  ButtonLink:({href,children}:{href:string;children:string})=>{harness.links[children]=href;return null;},
  Button:()=>null,Select:()=>null,Label:()=>null,State:()=>null,AnimatedList:()=>null,
  Skeleton:()=>null,StatusBadge:()=>null,BidiReference:()=>null,Checkbox:()=>null,
}));
function render(){harness.position=0;renderToStaticMarkup(createElement(SearchView));}
function edit(name:string,value:string){harness.inputs[name].onChange({target:{value}});render();}

describe('search draft navigation',()=>{
  it('retains unsent fields across next, first and locale changes and resets on changed criteria',()=>{
    harness.values=[];harness.params=new URLSearchParams('brand=Applied');
    render();
    edit('q','ساعة Watch ⌚');edit('brand','Unsent');edit('min_price','١٢٥٠٫٥٠');
    for(const cursor of ['next-page','']){
      harness.params=new URLSearchParams({brand:'Applied',cursor});render();
      expect(harness.inputs.q.value).toBe('ساعة Watch ⌚');
      expect(harness.inputs.brand.value).toBe('Unsent');
      expect(harness.inputs.min_price.value).toBe('١٢٥٠٫٥٠');
    }
    harness.pathname='/ar/search';render();
    expect(harness.inputs.min_price.value).toBe('١٢٥٠٫٥٠');
    harness.params=new URLSearchParams('brand=Changed');render();render();
    expect(harness.inputs.brand.value).toBe('Changed');
    expect(harness.inputs.q.value).toBe('');
    expect(harness.inputs.min_price.value).toBe('');
  });
});
