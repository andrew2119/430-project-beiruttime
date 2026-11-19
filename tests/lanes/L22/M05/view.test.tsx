import { Children, isValidElement, type ReactElement } from 'react';
import { expect, it, vi } from 'vitest';
import { Button, Input, Switch } from '@beirut-time/ui/foundation';
import type { Session } from '../../../../packages/contracts-identity/accounts';
import { Following } from '../../../../web/features/seller-follows/page';
import { ApiError } from '../../../../web/lib/api/client';
import { copy } from '../../../../web/features/seller-follows/copy';
const hooks=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,locale:'en',calls:[] as {path:string;body?:string}[],writeError:null as Error|null,readError:null as Error|null,retained:false}));
vi.mock('react',async()=>({...await vi.importActual<typeof import('react')>('react'),useEffect:(effect:()=>void)=>effect(),useState:(initial:unknown)=>{const i=hooks.cursor++;if(!(i in hooks.slots))hooks.slots[i]=initial;return [hooks.slots[i],(value:unknown)=>{hooks.slots[i]=value;}];},useRef:(initial:unknown)=>{const i=hooks.cursor++;if(!(i in hooks.slots))hooks.slots[i]={current:initial};return hooks.slots[i];}}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()})}));
vi.mock('../../../../web/shell/locale-context',()=>({useLocale:()=>hooks.locale}));
vi.mock('../../../../web/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:async(path:string,options?:{body?:string})=>{hooks.calls.push({path,body:options?.body});if(options?.body)throw hooks.writeError??new Error('unavailable');return {seller_id:'00000000-0000-4000-8000-000000000003',following:false,alerts_enabled:false,revision:0};}}));
vi.mock('../../../../web/lib/page-speed/read',()=>({usePageRead:()=>({data:{items:hooks.retained?[{seller_id:'00000000-0000-4000-8000-000000000003',following:true,alerts_enabled:true,revision:1,notice_revision:1,read_at:null,cleared_at:null,id:'private-notice',watch:'private-watch',occurred:'2026-11-17T00:00:00Z',sample:true}]:[],total:1000},error:hooks.readError,isPending:false,isError:!!hooks.readError,refetch:vi.fn()})}));
type Node=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Node[]{if(!isValidElement(value))return [];const node=value as Node;return [node,...Children.toArray(node.props.children as never).flatMap(nodes)];}
const session={access_fingerprint:'scope',principal:{actor:{subject_id:'00000000-0000-4000-8000-000000000002',organization_id:null},roles:['buyer']}} as Session;
function draw(){hooks.cursor=0;return nodes(Following({session}));}
it('retains mixed input, preference, page and exact pending operation across language changes without submitting',async()=>{
  hooks.slots=[];hooks.calls=[];hooks.locale='en';
  let view=draw();
  (view.find(n=>n.type===Input)!.props.onValueChange as (s:string)=>void)('00000000-0000-4000-8000-000000000003');
  (view.find(n=>n.type===Switch)!.props.onCheckedChange as (b:boolean)=>void)(true);
  (view.find(n=>n.type===Button&&n.props.children===copy.en.next)!.props.onClick as ()=>void)();
  view=draw();
  (view.find(n=>n.type==='form')!.props.onSubmit as (event:unknown)=>void)({preventDefault:vi.fn()});
  await vi.waitFor(()=>expect(hooks.calls.length).toBe(2));
  const payload=JSON.parse(hooks.calls[1].body!);
  view=draw();expect(view.some(n=>n.props.children===payload.operation_id)).toBe(true);
  hooks.locale='ar';view=draw();
  expect(view.find(n=>n.type===Input)!.props.value).toBe(payload.seller_id);
  expect(view.find(n=>n.type===Switch)!.props.checked).toBe(true);
  expect(view.some(n=>n.props.children===payload.operation_id)).toBe(true);
  expect(hooks.slots[0]).toBe(1);
  expect(hooks.calls).toHaveLength(2);
  const retry=view.find(n=>n.type===Button&&n.props.children===copy.ar.retry)!;
  (retry.props.onClick as ()=>void)();
  await vi.waitFor(()=>expect(hooks.calls.length).toBe(3));
  expect(JSON.parse(hooks.calls[2].body!)).toEqual(payload);
  (draw().find(n=>n.type===Input)!.props.onValueChange as (s:string)=>void)('مرجع Latin 👩🏽‍🔧 '.repeat(80));
  hooks.locale='en';expect(draw().find(n=>n.type===Input)!.props.value).toBe('مرجع Latin 👩🏽‍🔧 '.repeat(80));
});
it('provides complete matching recovery copy in both languages',()=>{
  expect(Object.keys(copy.ar).sort()).toEqual(Object.keys(copy.en).sort());
  expect(Object.values(copy.ar).every(Boolean)).toBe(true);
});

it('latches denied reads through refresh, unavailable answers and language changes',async()=>{
  for(const status of [401,403]) {
    hooks.slots=[];hooks.calls=[];hooks.writeError=null;hooks.locale='en';hooks.readError=null;hooks.retained=true;
    let view=draw();
    (view.find(node=>node.type===Input)!.props.onValueChange as (s:string)=>void)('private input');
    (view.find(node=>node.type===Button&&node.props.children===copy.en.unfollow)!.props.onClick as ()=>void)();
    await vi.waitFor(()=>expect(hooks.calls).toHaveLength(1));
    expect(draw().some(node=>node.props.children===copy.en.pending)).toBe(true);
    hooks.readError=new ApiError(status,'denied','');
    draw();
    for(const locale of ['en','ar']) {
      hooks.locale=locale;
      for(const error of [new ApiError(503,'unavailable',''),null]) {
        hooks.readError=error;view=draw();
        expect(view.some(node=>node.type===Input||node.type===Switch)).toBe(false);
        expect(view.some(node=>node.props.children==='private-watch'||node.props.children==='00000000-0000-4000-8000-000000000003')).toBe(false);
        expect(view.some(node=>node.props.children===copy[locale as 'en'|'ar'].pending)).toBe(false);
        (view.find(node=>node.type===Button)!.props.onClick as ()=>void)();
        expect(draw().some(node=>node.type===Input)).toBe(false);
      }
    }
    expect(hooks.slots[2]).toBe('');
    expect(hooks.slots[4]).toBe(null);
  }
  hooks.slots=[];hooks.locale='en';hooks.readError=null;hooks.retained=false;
});

it('clears private content after a denied write and keeps it hidden during refresh and locale changes',async()=>{
  for(const status of [401,403]) {
    hooks.slots=[];hooks.calls=[];hooks.locale='en';hooks.retained=true;hooks.readError=null;
    hooks.writeError=new ApiError(status,'denied','');
    let view=draw();
    expect(view.some(node=>node.props.children==='00000000-0000-4000-8000-000000000003')).toBe(true);
    (view.find(node=>node.type===Button&&node.props.children===copy.en.unfollow)!.props.onClick as ()=>void)();
    await vi.waitFor(()=>expect(hooks.calls).toHaveLength(1));
    await vi.waitFor(()=>expect(draw().some(node=>node.type===Input)).toBe(false));
    for(const locale of ['en','ar']) {
      hooks.locale=locale;view=draw();
      expect(view.some(node=>node.props.children==='00000000-0000-4000-8000-000000000003'||node.props.children==='private-watch')).toBe(false);
      expect(view.some(node=>node.type===Switch||node.type===Input)).toBe(false);
      expect(view.some(node=>node.props.children===copy[locale as 'en'|'ar'].pending)).toBe(false);
      (view.find(node=>node.type===Button)!.props.onClick as ()=>void)();
      expect(draw().some(node=>node.props.children==='00000000-0000-4000-8000-000000000003')).toBe(false);
    }
    expect(hooks.calls).toHaveLength(1);
  }
  hooks.slots=[];hooks.retained=false;hooks.writeError=null;hooks.locale='en';
});

it('retains the exact independent notice command during bilingual recovery',async()=>{
  for(const action of ['read','clear'] as const) {
    hooks.slots=[];hooks.calls=[];hooks.locale='en';hooks.retained=true;hooks.readError=null;hooks.writeError=null;
    let view=draw();
    (view.find(node=>node.type===Button&&node.props.children===copy.en[action])!.props.onClick as ()=>void)();
    await vi.waitFor(()=>expect(hooks.calls).toHaveLength(1));
    const command=JSON.parse(hooks.calls[0].body!);
    expect(command.action).toBe(action);
    expect(command.expected_revision).toBe(1);
    expect(command.notice_id).toBe('private-notice');
    expect(hooks.calls[0].path.endsWith('/notices')).toBe(true);
    hooks.locale='ar';view=draw();
    expect(view.some(node=>node.props.children===command.operation_id)).toBe(true);
    expect(view.some(node=>node.props.children===copy.ar.read)).toBe(true);
    expect(view.some(node=>node.props.children===copy.ar.clear)).toBe(true);
    (view.find(node=>node.type===Button&&node.props.children===copy.ar.retry)!.props.onClick as ()=>void)();
    await vi.waitFor(()=>expect(hooks.calls).toHaveLength(2));
    expect(JSON.parse(hooks.calls[1].body!)).toEqual(command);
  }
  hooks.slots=[];hooks.retained=false;hooks.locale='en';
});
