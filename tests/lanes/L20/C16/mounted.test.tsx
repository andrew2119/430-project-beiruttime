import React, { act } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { Command } from '../../../../packages/contracts-eligibility/private-review';

// A minimal document for mounted lifecycle checks; geometry remains a separate proof.
class Node {
  nodeType=1; nodeName='DIV'; tagName='DIV'; namespaceURI='http://www.w3.org/1999/xhtml';
  parentNode:Node|null=null; childNodes:Node[]=[]; ownerDocument:Node;
  style={setProperty:()=>{}}; attributes:Record<string,string>={}; value=''; text='';
  constructor(document?:Node) {this.ownerDocument=document ?? this;}
  appendChild(child:Node) {child.parentNode?.removeChild(child);this.childNodes.push(child);child.parentNode=this;return child;}
  insertBefore(child:Node,before:Node) {child.parentNode?.removeChild(child);this.childNodes.splice(this.childNodes.indexOf(before),0,child);child.parentNode=this;return child;}
  removeChild(child:Node) {this.childNodes.splice(this.childNodes.indexOf(child),1);child.parentNode=null;return child;}
  setAttribute(key:string,value:string) {this.attributes[key]=value;}
  removeAttribute(key:string) {delete this.attributes[key];}
  addEventListener() {} removeEventListener() {}
  get textContent():string {return this.text+this.childNodes.map(child=>child.textContent).join('');}
  set textContent(value:string) {this.text=value;this.childNodes=[];}
  createElement(tag:string) {const node=new Node(this);node.nodeName=node.tagName=tag.toUpperCase();return node;}
  createElementNS(_namespace:string,tag:string) {return this.createElement(tag);}
  createTextNode(text:string) {const node=new Node(this);node.nodeType=3;node.text=text;return node;}
}
const state=vi.hoisted(()=>({error:null as unknown,historyError:null as unknown,source:1,access:'access-one',locale:'en' as 'en'|'ar',buttons:new Map<string,()=>unknown>(),input:null as null|((value:string)=>void),reason:''}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:state.access})}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:{key:unknown[]})=>read.key[0]==='private-review-v1'?{
  isPending:false,error:state.error,data:{case_id:'case-one',assignment_revision:1,revision:2,state:'under_review',binding:{source_revision:state.source}},refetch:async()=>({error:state.error}),
}:{isPending:false,error:state.historyError,data:{items:[],total:0,page:1,page_size:25},refetch:vi.fn()}}));
vi.mock('../../../../web/features/eligibility-review/api',()=>({
  reviewRead:()=>({key:['private-review-v1']}),historyRead:()=>({key:['history']}),
  sendCommand:vi.fn(),readEvidence:vi.fn(async()=>({synthetic:true,identity_match:'match',document_valid:true})),
}));
vi.mock('../../../../packages/ui/src/foundation/index.ts',()=>({
  Button:({children,onClick}:{children:string;onClick:()=>unknown})=>{state.buttons.set(children,onClick);return <button>{children}</button>;},
  Card:({children}:{children:React.ReactNode})=><div>{children}</div>,
  State:({title,body,children}:{title:string;body:string;children:React.ReactNode})=><div>{title}{body}{children}</div>,
  Textarea:({value,onValueChange}:{value:string;onValueChange:(value:string)=>void})=>{state.input=onValueChange;state.reason=value;return <textarea value={value} readOnly/>;},
  formatNumber:(value:number)=>String(value),
}));
vi.mock('@/shell/foundation/page',()=>({
  PageFrame:({children}:{children:React.ReactNode})=><div>{children}</div>,PageBody:({children}:{children:React.ReactNode})=><div>{children}</div>,
  PageHeader:({title}:{title:string})=><h1>{title}</h1>,PageLoading:()=>null,
}));
import ReviewView from '../../../../web/features/eligibility-review/view';
import { sendCommand } from '../../../../web/features/eligibility-review/api';
import { ApiError } from '../../../../web/lib/api/client';
import { copy } from '../../../../web/features/eligibility-review/copy';
import { createRoot, type Root } from 'react-dom/client';
let root:Root, container:Node;
async function render() {state.buttons.clear();await act(async()=>root.render(<ReviewView caseId="case-one"/>));}
async function press(label:string) {await act(async()=>{await state.buttons.get(label)!();});}
beforeEach(async()=>{
  const document=new Node();document.nodeType=9;
  vi.stubGlobal('document',document);vi.stubGlobal('window',{HTMLIFrameElement:class {},event:undefined});
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  state.error=null;state.historyError=null;state.source=1;state.access='access-one';state.locale='en';state.buttons.clear();
  vi.mocked(sendCommand).mockReset().mockRejectedValue(new Error('Response unavailable'));
  container=new Node(document);root=createRoot(container as unknown as HTMLElement);await render();
  expect(state.input).toBeTypeOf('function');
});
afterEach(async()=>{await act(async()=>root.unmount());vi.unstubAllGlobals();});
it('retains the exact pending command through failed refresh, source change and language change',async()=>{
  await act(async()=>state.input!('Synthetic finding'));
  await press(copy.en.correct);
  const original=vi.mocked(sendCommand).mock.calls[0][1];
  state.error=new ApiError(503,'unavailable','request');await render();
  expect(container.textContent).not.toContain(original.operation_id);
  await press(copy.en.retry);
  state.error=null;state.source=2;await press(copy.en.retry);state.locale='ar';await render();
  expect(container.textContent).toContain(original.operation_id);
  await press(copy.ar.retry);
  expect(vi.mocked(sendCommand).mock.calls[1][1]).toEqual(original);
});
it('clears evidence, reason and pending command after history denial and recovery',async()=>{
  await act(async()=>state.input!('Private finding'));
  await press(copy.en.evidence);await press(copy.en.correct);
  const original=vi.mocked(sendCommand).mock.calls[0][1] as Command;
  state.historyError=new ApiError(403,'denied','request');await render();
  expect(container.textContent).toContain(copy.en.denied);
  state.historyError=null;await press(copy.en.retry);await render();
  expect(state.reason).toBe('');
  expect(container.textContent).not.toContain(copy.en.match);
  expect(container.textContent).not.toContain(original.operation_id);
  await act(async()=>state.input!('New finding'));await press(copy.en.correct);
  expect(vi.mocked(sendCommand).mock.calls[1][1].operation_id).not.toBe(original.operation_id);
});
it('drops pending data when the access identity changes',async()=>{
  await act(async()=>state.input!('Private finding'));await press(copy.en.correct);
  const original=vi.mocked(sendCommand).mock.calls[0][1];state.access='access-two';await render();
  expect(state.reason).toBe('');expect(container.textContent).not.toContain(original.operation_id);
});

it('keeps the reference when refresh removes the form before the response is lost',async()=>{
  let loseResponse!:(reason:Error)=>void;
  vi.mocked(sendCommand).mockImplementationOnce(()=>new Promise((_resolve,reject)=>{loseResponse=reject;}));
  await act(async()=>state.input!('Synthetic finding'));
  await press(copy.en.correct);
  const original=vi.mocked(sendCommand).mock.calls[0][1];
  state.error=new ApiError(503,'unavailable','request');await render();
  await act(async()=>{loseResponse(new Error('Response unavailable'));});
  state.error=null;await render();
  expect(container.textContent).toContain(original.operation_id);
  await press(copy.en.retry);
  expect(vi.mocked(sendCommand).mock.calls[1][1]).toEqual(original);
});
