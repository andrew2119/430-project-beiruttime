import { Children, isValidElement, type ReactElement } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
const current=vi.hoisted(()=>({locale:'en' as 'en'|'ar',offset:undefined as number|undefined,read:undefined as unknown,data:undefined as unknown,error:false}));
vi.mock('react',async()=>({...await vi.importActual<typeof import('react')>('react'),useState:(initial:number)=>{current.offset??=initial;return [current.offset,(next:number)=>{current.offset=next;}];}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>current.locale}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:unknown)=>{current.read=read;return {data:current.data,isError:current.error,isPending:!current.data&&!current.error,isFetching:false,refetch:vi.fn()};}}));
vi.mock('../../../../web/features/similar-watches/read',()=>({similarRead:(query:unknown)=>query}));
import View from '../../../../web/features/similar-watches/view';
import fixtures from '../../../../packages/contracts-catalog/similar-watches/fixtures.json';
import { Button, State } from '@beirut-time/ui/foundation';
type Element=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Element[]{if(!isValidElement(value))return [];const element=value as Element;return [element,...Children.toArray(element.props.children as never).flatMap(nodes)];}
const query={operation_id:fixtures.success.operation_id,subject_id:fixtures.success.subject_id,expected_revision:1,offset:0};
beforeEach(()=>{current.locale='en';current.offset=undefined;current.data=fixtures.success;current.error=false;});
it('preserves the exact operation and selected page on an in-place language change',()=>{
  current.data={...fixtures.success,next_offset:20};
  const first=nodes(View({initialQuery:query}));
  const next=first.find(node=>node.type===Button&&node.props.children==='Next page')!;
  (next.props.onClick as ()=>void)();current.locale='ar';
  const translated=nodes(View({initialQuery:query}));
  expect(current.read).toEqual({...query,offset:20});
  expect(translated.some(node=>node.props.children==='الصفحة الأولى')).toBe(true);
});
it('renders every recovery state in both languages and hides retained data on failure',()=>{
  for(const locale of ['en','ar'] as const)for(const state of ['empty','denied','stale','unavailable'] as const){
    current.locale=locale;current.data=fixtures[state==='unavailable'?'lost_response':state];
    const view=nodes(View({initialQuery:query}));const stateNode=view.find(node=>node.type===State)!;
    expect(stateNode.props.title).toBeTruthy();expect(stateNode.props.body).toBeTruthy();
    expect(view.filter(node=>node.type===Button)).toHaveLength(1);
  }
  current.data=fixtures.success;current.error=true;
  expect(nodes(View({initialQuery:query})).some(node=>node.props.children===fixtures.success.items[0].watch.title)).toBe(false);
});
