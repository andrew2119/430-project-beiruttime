import { beforeEach, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Button, ButtonLink, Segmented, State } from '@beirut-time/ui/foundation';
import { Requests, DataRecord } from '../../../../web/features/personal-data/view';
import { copy } from '../../../../web/features/personal-data/copy';
import pending from '../../../../packages/contracts-identity/data-requests/fixtures/lost-response.v1.json';
import type { DataOperation } from '../../../../packages/contracts-identity/data-requests';
const hooks=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,locale:'en',data:{items:[],total:0},error:null as unknown,submit:vi.fn(),lookup:vi.fn(),refetch:vi.fn()}));
vi.mock('react',async()=>{
  const actual=await vi.importActual<typeof import('react')>('react');
  return {...actual,useEffect:()=>{},useRef:(initial:unknown)=>{const at=hooks.cursor++;if (!(at in hooks.slots)) hooks.slots[at]={current:initial};return hooks.slots[at];},useState:(initial:unknown)=>{const at=hooks.cursor++;if (!(at in hooks.slots)) hooks.slots[at]=initial;return [hooks.slots[at],(next:unknown)=>{hooks.slots[at]=typeof next === 'function'?next(hooks.slots[at]):next;}];}};
});
vi.mock('@/shell/locale-context',()=>({useLocale:()=>hooks.locale}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:hooks.data,error:hooks.error,isPending:false,isFetching:false,refetch:hooks.refetch})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,useSessionState:()=> 'signed-out'}));
vi.mock('../../../../web/features/personal-data/read',()=>({personalDataRead:vi.fn(),submitDataRequest:hooks.submit,lookupDataRequest:hooks.lookup}));
type Element=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Element[] {if (!isValidElement(value)) return [];const element=value as Element;return [element,...Children.toArray(element.props.children as never).flatMap(nodes)];}
function draw() {hooks.cursor=0;return Requests({fingerprint:'scope-1',accessToken:'synthetic-token'});}
function action(view:unknown,label:string) {return nodes(view).find(node=>node.type===Button && node.props.children===label)!;}
async function click(view:unknown,label:string) {await (action(view,label).props.onClick as ()=>Promise<void>)();await Promise.resolve();await Promise.resolve();}
beforeEach(()=>{hooks.slots=[];hooks.cursor=0;hooks.locale='en';hooks.data={items:[],total:0};hooks.error=null;hooks.submit.mockReset();hooks.lookup.mockReset();hooks.refetch.mockReset();});
it('keeps the exact uncertain command and selected kind across language changes and retries',async()=>{
  hooks.submit.mockRejectedValue(new Error('unavailable'));
  await click(draw(),copy.en.submit);
  const command=hooks.submit.mock.calls[0][1];
  hooks.locale='ar';const arabic=draw();
  expect(nodes(arabic).find(node=>node.type===Segmented)?.props.value).toBe('export');
  expect(nodes(arabic).find(node=>node.type===Segmented)?.props.disabled).toBe(true);
  await click(arabic,copy.ar.submit);
  expect(hooks.submit.mock.calls[1][1]).toEqual(command);
  expect(JSON.stringify(nodes(draw()).filter(node=>node.type==='bdi').map(node=>node.props.children))).toContain(command.operation_id);
});
it('retains page and supports the server total beyond a thousand-row boundary',async()=>{
  hooks.data={items:[],total:1000};await click(draw(),copy.en.next);
  hooks.locale='ar';expect(action(draw(),copy.ar.previous).props.disabled).toBe(false);
  for (let page=1;page<50;page++) await click(draw(),copy.ar.next);
  expect(action(draw(),copy.ar.next).props.disabled).toBe(true);
});
it('clears displayed private records when the current read is denied',async()=>{
  const {ApiError}=await import('../../../../web/lib/api/client');
  hooks.error=new ApiError(403,'denied','');
  const view=draw();expect(nodes(view).find(node=>node.type===State)?.props.title).toBe(copy.en.denied);
  expect(nodes(view).some(node=>node.type===DataRecord)).toBe(false);
});
it('renders all domains, reasoned holds, absent dates and mixed identifiers in both languages',()=>{
  const operation={...pending,operation_id:'طلب-LONG-⌚-١٢٣',state:'held',domains:{orders:{state:'retained',reasons:['custody','dispute']}},next_review_at:null} as DataOperation;
  for (const locale of ['en','ar'] as const) {
    const markup=renderToStaticMarkup(<DataRecord operation={operation} t={copy[locale]} locale={locale} busy={false} onDownload={()=>{}}/>);
    expect(markup).toContain(copy[locale].custody);expect(markup).toContain(copy[locale].dispute);
    expect(markup).toContain(copy[locale].identity);expect(markup).toContain(copy[locale]['service-operations']);
    expect(markup).toContain('طلب-LONG-⌚-١٢٣');expect(markup).not.toContain('undefined');
  }
});

it('quarantines retained history through denied and unsuccessful recovery reads',async()=>{
  const {ApiError}=await import('../../../../web/lib/api/client');
  hooks.data={items:[pending as never],total:1};
  hooks.submit.mockRejectedValue(new ApiError(403,'denied',''));
  await click(draw(),copy.en.submit);
  expect(nodes(draw()).some(node=>node.type===DataRecord)).toBe(false);
  hooks.refetch.mockResolvedValue({isSuccess:false});
  await click(draw(),copy.en.retry);
  expect(nodes(draw()).some(node=>node.type===DataRecord)).toBe(false);
  hooks.refetch.mockResolvedValue({isSuccess:true});
  await click(draw(),copy.en.retry);
  expect(nodes(draw()).some(node=>node.type===DataRecord)).toBe(true);
});
it('offers a locale-aware support destination',()=>{
  for (const locale of ['en','ar']) {
    hooks.locale=locale;
    expect(nodes(draw()).find(node=>node.type===ButtonLink && node.props.children===copy[locale as 'en'|'ar'].support)?.props.href).toBe(`/${locale}/inbox`);
  }
});
it.each(['en','ar'] as const)('preserves an unresolved reference after access recovery in %s',async(locale)=>{
  const {ApiError}=await import('../../../../web/lib/api/client');
  hooks.submit.mockRejectedValueOnce(new Error('unavailable'))
    .mockRejectedValueOnce(new ApiError(403,'denied',''))
    .mockRejectedValueOnce(new Error('unavailable'));
  await click(draw(),copy.en.submit);
  const command=hooks.submit.mock.calls[0][1];
  await click(draw(),copy.en.submit);
  expect(nodes(draw()).some(node=>node.type===DataRecord)).toBe(false);
  hooks.locale=locale;
  hooks.refetch.mockResolvedValue({isSuccess:true});
  await click(draw(),copy[locale].retry);
  const recovered=draw();
  expect(nodes(recovered).find(node=>node.type===Segmented)?.props.disabled).toBe(true);
  expect(nodes(recovered).filter(node=>node.type==='bdi').map(node=>node.props.children)).toContain(command.operation_id);
  await click(recovered,copy[locale].submit);
  expect(hooks.submit.mock.calls.map(call=>call[1])).toEqual([command,command,command]);
  hooks.lookup.mockResolvedValue({...pending,operation_id:command.operation_id});
  await click(draw(),copy[locale].lookup);
  expect(hooks.lookup).toHaveBeenCalledWith('scope-1',command.operation_id);
  expect(nodes(draw()).find(node=>node.type===Segmented)?.props.disabled).toBe(false);
  expect(nodes(draw()).find(node=>node.type===DataRecord)?.props.operation).toEqual({...pending,operation_id:command.operation_id});
});
