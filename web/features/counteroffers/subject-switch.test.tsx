import { act, type ReactNode } from 'react';
import { expect, it, vi } from 'vitest';
import View from './view';
import { LocaleContext } from '@/shell/locale-context';
import type { Command, Counter, Operation } from '@contracts/contracts-pricing/counteroffers';
import fixture from '../../../packages/contracts-pricing/counteroffers/fixtures/success.v1.json';

const state=vi.hoisted(()=>({counter:null as Counter|null}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.counter,isSuccess:true,refetch:vi.fn()})}));
vi.mock('@beirut-time/ui/foundation',()=>({
  Button:({children,...props}:{children:ReactNode})=><button {...props}>{children}</button>,
  Card:({children}:{children:ReactNode})=><div>{children}</div>,
  Input:(props:object)=><input {...props}/>,
  Checkbox:(props:object)=><input {...props}/>,
  State:({body,children}:{body:string;children:ReactNode})=><div>{body}{children}</div>,
  formatAmount:(value:string)=>value,
}));
vi.mock('@/shell/foundation/page',()=>({
  PageFrame:({children}:{children:ReactNode})=><div>{children}</div>,
  PageBody:({children}:{children:ReactNode})=><div>{children}</div>,
  PageHeader:()=>null,
}));

type Node={props:Record<string,unknown>};
type Mounted={update:(node:ReactNode)=>void;unmount:()=>void;root:{findAllByType:(type:string)=>Node[]};toJSON:()=>unknown};
type Renderer={create:(node:ReactNode)=>Mounted};
// A mounted component runner is optional in this isolated check environment.
const runnerName='react-test-renderer';
const runner=await import(/* @vite-ignore */ runnerName).catch(()=>null) as Renderer|null;
it.skipIf(!runner)('clears the mounted form on subject switch and ignores the old completion',async()=>{
  const sent=fixture.current as Counter;
  state.counter=sent;
  let complete!:(answer:Operation)=>void;
  const send=vi.fn<(command:Command)=>Promise<Operation>>(()=>new Promise<Operation>(resolve=>{complete=resolve;}));
  const lookup=vi.fn();
  const quote=vi.fn();
  const terms={quote_id:sent.economics.quote_id,quote_revision:1,terms_revision:1,
    en:{terms:'Terms',returns:'Returns',assurance:'Assurance'},
    ar:{terms:'الشروط',returns:'الإرجاع',assurance:'الضمان'},support_href:'/support'};
  const screen=(counter:Counter,locale:'en'|'ar'='en')=><LocaleContext value={locale}><View
    scope="same-access" subjectId={counter.subject_id} watchId={counter.watch_id} actor={sent.buyer_id}
    sourceRevision={3} authorityRevision={2} read={null} send={send} lookup={lookup} quote={quote} terms={terms}/></LocaleContext>;
  let mounted!:Mounted;
  await act(async()=>{mounted=runner!.create(screen(sent));});
  const review=mounted.root.findAllByType('input').find(node=>'onCheckedChange' in node.props)!;
  await act(async()=>{(review.props.onCheckedChange as (value:boolean)=>void)(true);});
  await act(async()=>{const button=mounted.root.findAllByType('button').find(node=>node.props.children==='Accept current counteroffer')!;
    (button.props.onClick as ()=>void)();});
  const command=send.mock.calls[0][0];
  expect(command).toBeDefined();
  const pending=JSON.stringify(mounted.toJSON());
  await act(async()=>{mounted.update(screen(sent,'ar'));});
  expect(send).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(mounted.toJSON())).toContain('مرجع الإجراء');
  expect(pending).toContain('Action reference');
  const next={...sent,subject_id:'next-subject',watch_id:'next-watch',revision:1};
  state.counter=next;
  await act(async()=>{mounted.update(screen(next));});
  expect(JSON.stringify(mounted.toJSON())).not.toContain('Action reference');
  await act(async()=>{complete({...fixture.operation,...command,state:'succeeded',current:{...sent,revision:10}} as Operation);});
  expect(JSON.stringify(mounted.toJSON())).not.toContain('Action reference');
  expect(mounted.root.findAllByType('input').find(node=>'checked' in node.props)?.props.checked).toBe(false);
  expect(send).toHaveBeenCalledTimes(1);
  expect(lookup).not.toHaveBeenCalled();
  await act(async()=>{mounted.unmount();});
});
