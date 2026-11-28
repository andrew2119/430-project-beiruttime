import {Children,isValidElement,type ReactElement} from 'react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {Button,Textarea} from '@beirut-time/ui/foundation';
import {ApiError} from '@/lib/api/client';
import {BuyerSupport} from './buyer-support';
import type {SupportConversation} from './support-api';

type Effect=()=>void|(()=>void);
const state=vi.hoisted(()=>({index:0,slots:[] as unknown[],effects:[] as Effect[],read:vi.fn(),request:vi.fn(),buyer:1}));
vi.mock('react',async()=>({...await vi.importActual('react'),useSyncExternalStore:(_:unknown,get:()=>unknown)=>get(),useEffect:(effect:Effect,deps:unknown[])=>{
    const index=state.index++;
    const previous=state.slots[index] as unknown[]|undefined;
    if(!previous||deps.some((value,index)=>value!==previous[index])) {state.slots[index]=deps;state.effects.push(effect);}
  },
  useRef:(initial:unknown)=>{
    const index=state.index++;
    if(!(index in state.slots)) state.slots[index]={current:initial};
    return state.slots[index];
  },
  useState:(initial:unknown)=>{
    const index=state.index++;
    if(!(index in state.slots)) state.slots[index]=initial;
    return [state.slots[index],(value:unknown)=>{state.slots[index]=typeof value==='function'?value(state.slots[index]):value;}];
  }}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:state.read}));
vi.mock('./session',()=>({
  useBuyerSession:()=>({state:'authenticated',signedIn:true,roles:['buyer'],organizationId:null,
    subjectId:id(state.buyer),fingerprint:`test-buyer-${state.buyer}`}),
  authenticatedRequest:state.request,
}));

const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const conversation:SupportConversation={schema_version:1,auction_id:id(2),buyer_id:id(1),conversation_id:id(3),order_id:null,
  revision:2,hold_state:'active',assignment_state:'awaiting_operator',operator_id:null,follow_up_due_at:'2030-01-02T10:00:00Z',
  escalate_at:'2030-01-03T10:00:00Z',items:[{sequence:2,author:'support',body:'Latest reply',sent_at:'2030-01-02T10:00:00Z'}],
  next_cursor:'old-page'};
const unopened=new ApiError(404,'support_not_open','');

type Node=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Node[] {
  if(!isValidElement(value)) return [];
  const node=value as Node;
  return [node,...Children.toArray(node.props.children as never).flatMap(nodes)];
}
function draw(historyOnly=false) {
  state.index=0;
  const boundary=Children.toArray(BuyerSupport({auctionId:id(2),listingId:id(4),historyOnly}).props.children).at(-1) as Node;
  return nodes((boundary.type as (props:unknown)=>Node)(boundary.props));
}
async function advance() {for(let step=0;step<8;step++) await Promise.resolve();}
async function click(label:string,historyOnly=false) {
  const action=draw(historyOnly).find(node=>node.type===Button&&node.props.children===label);
  expect(action).toBeDefined();
  (action!.props.onClick as ()=>void)();
  await advance();
}
async function submit() {
  const form=draw().find(node=>node.type==='form');
  expect(form).toBeDefined();
  (form!.props.onSubmit as (event:unknown)=>void)({preventDefault(){}});
  await advance();
}
function remount() {state.slots=[];state.effects=[];}
const browserStorage=new Map<string,string>();
function freshDocument() {
  remount();
  vi.stubGlobal('sessionStorage',{
    getItem:(key:string)=>browserStorage.get(key)??null,
    setItem:(key:string,value:string)=>{browserStorage.set(key,value);},
    removeItem:(key:string)=>{browserStorage.delete(key);},
  });
}
const reply=(operation_id:string,state:'prepared'|'accepted'|'abandoned'|'stale',revision:number)=>
  ({schema_version:1,operation_id,conversation_id:id(3),auction_id:id(2),buyer_id:id(1),state,revision});
const keyOf=(options:{headers:Record<string,string>})=>options.headers['Idempotency-Key'];
beforeEach(()=>{browserStorage.clear();freshDocument();state.buyer=1;state.read.mockReset();state.request.mockReset();});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

it.each([401,403,503])('revalidates mounted history and hides retained messages on %s without changing the buyer',async status=>{
  vi.useFakeTimers();
  let answer:Record<string,unknown>={data:conversation,isFetchedAfterMount:true};
  const refetch=vi.fn(async()=>{
    answer={...answer,isError:true,error:new ApiError(status,'unavailable','')};
  });
  state.read.mockImplementation(()=>({...answer,refetch}));
  expect(draw(true).some(node=>node.props.children==='Latest reply')).toBe(true);
  const cleanup=state.effects.splice(0).map(effect=>effect());
  try {
    await vi.advanceTimersByTimeAsync(15000);
    expect(refetch).toHaveBeenCalledExactlyOnceWith({cancelRefetch:false});
    const visible=draw(true);
    expect(visible.some(node=>node.props.children==='Latest reply'||node.type===Textarea)).toBe(false);
    expect(visible.some(node=>node.props.title===(status===503?'Support is temporarily unavailable':'You do not have access to this conversation.'))).toBe(true);
    expect(visible.some(node=>node.props.children==='Open support conversation')).toBe(false);
    expect(state.request).not.toHaveBeenCalled();
  } finally {for(const stop of cleanup) stop?.();}
});

it('leaves an expired older cursor without clearing the pending message or exposing cached messages',async()=>{
  const refetch=vi.fn();
  state.read.mockImplementation((read:{key:readonly unknown[]})=>read.key.at(-1)==='old-page'
    ?{data:conversation,isError:true,isFetchedAfterMount:true,error:new ApiError(409,'stale_cursor',''),refetch}
    :{data:conversation,isFetchedAfterMount:true,refetch});
  const draft=draw().find(node=>node.type===Textarea)!;
  (draft.props.onValueChange as (text:string)=>void)('Is there an update?');
  state.request.mockImplementationOnce((_url,options)=>Promise.resolve(reply(keyOf(options),'prepared',2)))
    .mockRejectedValueOnce(new ApiError(503,'unavailable',''));
  await submit();
  expect(state.request).toHaveBeenCalledTimes(2);
  const original=state.request.mock.calls[1];
  await click('Older messages');
  expect(draw().some(node=>node.props.children==='Latest reply')).toBe(false);
  await click('Latest messages');
  expect(draw().find(node=>node.type===Textarea)?.props).toMatchObject({value:'Is there an update?',disabled:true});
  state.request.mockResolvedValueOnce({schema_version:1,operation_id:original[1].headers['Idempotency-Key'],
    conversation_id:id(3),auction_id:id(2),buyer_id:id(1),state:'accepted',revision:3});
  await submit();
  expect(state.request).toHaveBeenCalledTimes(3);
  expect(state.request.mock.calls[2][0]).toBe(original[0]);
  expect(state.request.mock.calls[2][1]).toMatchObject({headers:original[1].headers,body:original[1].body});
  expect(draw().find(node=>node.type===Textarea)?.props.value).toBe('');
});

it.each(['committed','never arrived','never prepared'])('recovers a single bound operation in a fresh document when it %s',async delivery=>{
  const refetch=vi.fn();
  const text=`Private update: ${delivery}`;
  const messages=new Map<string,string>();
  const prepared=new Map<string,string>();
  state.read.mockReturnValue({data:conversation,isFetchedAfterMount:true,refetch});
  (draw().find(node=>node.type===Textarea)!.props.onValueChange as (text:string)=>void)(text);
  state.request.mockImplementationOnce(async(url,options)=>{
    expect(url).toMatch(/\/prepare$/);
    const key=keyOf(options);
    expect(JSON.stringify([...browserStorage])).not.toContain(text);
    if(delivery==='never prepared') throw new ApiError(503,'unavailable','');
    prepared.set(key,JSON.parse(options.body).body);
    return reply(key,'prepared',2);
  });
  if(delivery!=='never prepared') state.request.mockImplementationOnce(async(url,options)=>{
    expect(url).toMatch(/\/deliver$/);
    const key=keyOf(options);
    if(delivery==='committed') messages.set(key,prepared.get(key)!);
    throw new ApiError(503,'unavailable','');
  });
  await submit();
  const key=keyOf(state.request.mock.calls[0][1]);
  const count=delivery==='never prepared'?1:2;
  expect([...browserStorage.values()]).toEqual([`${key}:${id(3)}`]);
  freshDocument();
  const newer={...conversation,revision:delivery==='committed'?3:2};
  state.read.mockReturnValue({data:newer,isFetchedAfterMount:false,refetch});
  expect(draw().some(node=>node.type===Textarea)).toBe(false);
  state.read.mockReturnValue({data:newer,isFetchedAfterMount:true,refetch});
  expect(draw(true).some(node=>node.type===Textarea)).toBe(false);
  state.buyer=9;
  state.read.mockReturnValue({data:{...newer,buyer_id:id(9)},isFetchedAfterMount:true,refetch});
  expect(draw().find(node=>node.type===Textarea)?.props).toMatchObject({value:'',disabled:false});
  expect(state.request).toHaveBeenCalledTimes(count);
  freshDocument();state.buyer=1;
  state.read.mockReturnValue({data:newer,isFetchedAfterMount:true,refetch});
  expect(draw().find(node=>node.type===Textarea)?.props).toMatchObject({value:'',disabled:true});
  state.request.mockImplementationOnce(async(url,options)=>{
    expect(url).toContain(`/message-attempts/${key}/deliver`);
    expect(keyOf(options)).toBe(key);
    expect(JSON.parse(options.body)).toEqual({conversation_id:id(3)});
    if(!prepared.has(key)) return reply(key,'abandoned',2);
    if(!messages.has(key)) messages.set(key,prepared.get(key)!);
    return reply(key,'accepted',3);
  });
  await submit();
  expect([...messages.values()]).toEqual(delivery==='never prepared'?[]:[text]);
  expect(browserStorage.size).toBe(0);
  freshDocument();
  expect(draw().find(node=>node.type===Textarea)?.props).toMatchObject({value:'',disabled:false});
});

it.each(['committed','never delivered','hold reactivated'])('checks a held message without delivery from history when it %s',async delivery=>{
  const refetch=vi.fn();
  const text='Original private update';
  const receipts=new Map<string,string>();
  state.read.mockReturnValue({data:conversation,isFetchedAfterMount:true,refetch});
  (draw().find(node=>node.type===Textarea)!.props.onValueChange as (value:string)=>void)(text);
  state.request.mockImplementationOnce(async(_url,options)=>reply(keyOf(options),'prepared',2))
    .mockImplementationOnce(async(_url,options)=>{
      if(delivery==='committed') receipts.set(keyOf(options),text);
      throw new ApiError(503,'unavailable','');
    });
  await submit();
  const original=state.request.mock.calls[1];
  freshDocument();
  const resolved={...conversation,revision:4,order_id:id(6),hold_state:delivery==='hold reactivated'?'active':'resolved'};
  state.read.mockReturnValue({data:resolved,isFetchedAfterMount:false,refetch});
  expect(draw(true).some(node=>node.props.children==='Check previous message')).toBe(false);
  state.read.mockReturnValue({data:resolved,isFetchedAfterMount:true,refetch});
  expect(draw(true).some(node=>node.type===Textarea||node.props.children==='Open support conversation')).toBe(false);
  state.request.mockImplementationOnce(async(url,options)=>{
    expect(url).toBe(original[0].replace(/\/deliver$/,'/check'));
    expect(options).toMatchObject({headers:original[1].headers,body:original[1].body});
    const key=keyOf(options);
    if(delivery==='hold reactivated') return reply(key,'prepared',4);
    return receipts.has(key)?reply(key,'accepted',3):reply(key,'stale',4);
  });
  await click('Check previous message',true);
  expect(state.request).toHaveBeenCalledTimes(3);
  expect([...receipts.values()]).toEqual(delivery==='committed'?[text]:[]);
  const shown=draw(true);
  if(delivery==='hold reactivated') {
    expect(browserStorage.size).toBe(1);
    expect(shown.some(node=>node.props.children==='The previous message is saved but has not been sent.')).toBe(true);
    expect(shown.some(node=>node.props.children==='Go to conversation to retry sending')).toBe(true);
    expect(shown.some(node=>node.type===Textarea)).toBe(false);
    return;
  }
  expect(browserStorage.size).toBe(0);
  expect(shown.some(node=>node.props.children==='Check previous message'||node.type===Textarea)).toBe(false);
  const feedback=delivery==='committed'?'Message confirmed':'The previous message was not sent. This conversation has not been reopened.';
  expect(shown.some(node=>node.props.children===feedback)).toBe(true);
});

it.each([404,503,'bad receipt'] as const)('keeps the original check retry visible and reports %s without claiming a send result',async failure=>{
  const attempt=id(7);
  browserStorage.set(`bt.support-attempt.v1:${id(1)}:${id(2)}`,`${attempt}:${id(3)}`);
  state.read.mockReturnValue({data:{...conversation,hold_state:'resolved'},isFetchedAfterMount:true,refetch:vi.fn()});
  if(failure==='bad receipt') state.request.mockResolvedValueOnce(reply(id(9),'accepted',3));
  else state.request.mockRejectedValueOnce(new ApiError(failure,'unavailable',''));
  await click('Check previous message',true);
  expect(draw(true).some(node=>node.props.children==='Message status is temporarily unavailable. Check the same message again.')).toBe(true);
  expect([...browserStorage.values()]).toEqual([`${attempt}:${id(3)}`]);
  state.request.mockResolvedValueOnce(reply(attempt,'accepted',3));
  await click('Check previous message',true);
  expect(state.request.mock.calls[1][0]).toBe(state.request.mock.calls[0][0]);
  expect(state.request.mock.calls[1][1]).toMatchObject({headers:state.request.mock.calls[0][1].headers,body:state.request.mock.calls[0][1].body});
  expect(draw(true).some(node=>node.props.children==='Message confirmed')).toBe(true);
});

it('turns an open active URL read-only after the current hold resolves',async()=>{
  vi.useFakeTimers();
  const attempt=id(7);
  browserStorage.set(`bt.support-attempt.v1:${id(1)}:${id(2)}`,`${attempt}:${id(3)}`);
  let page:SupportConversation=conversation;
  const refetch=vi.fn(async()=>{page={...page,hold_state:'resolved',revision:3};});
  state.read.mockImplementation(()=>({data:page,isFetchedAfterMount:true,refetch}));
  expect(draw().some(node=>node.type===Textarea)).toBe(true);
  const cleanup=state.effects.splice(0).map(effect=>effect());
  try {
    await vi.advanceTimersByTimeAsync(15000);
    expect(draw().some(node=>node.type===Textarea||node.props.title==='No support operator has been assigned yet')).toBe(false);
    state.request.mockResolvedValueOnce(reply(attempt,'stale',3));
    await click('Check previous message');
    expect(state.request).toHaveBeenCalledTimes(1);
    expect(state.request.mock.calls[0][0]).toMatch(/\/check$/);
    expect(browserStorage.size).toBe(0);
  } finally {for(const stop of cleanup) stop?.();}
});

it('does not show a composer when resolution lands between history check and active entry',async()=>{
  const attempt=id(7);
  browserStorage.set(`bt.support-attempt.v1:${id(1)}:${id(2)}`,`${attempt}:${id(3)}`);
  const refetch=vi.fn();
  state.read.mockReturnValue({data:conversation,isFetchedAfterMount:true,refetch});
  state.request.mockResolvedValueOnce(reply(attempt,'prepared',2));
  await click('Check previous message',true);
  expect(draw(true).some(node=>node.props.children==='Go to conversation to retry sending')).toBe(true);
  freshDocument();
  state.read.mockReturnValue({data:{...conversation,hold_state:'resolved',revision:3},isFetchedAfterMount:true,refetch});
  expect(draw().some(node=>node.type===Textarea||node.props.children==='Open support conversation')).toBe(false);
  state.request.mockResolvedValueOnce(reply(attempt,'stale',3));
  await click('Check previous message');
  expect(state.request.mock.calls.map(call=>call[0])).toEqual(Array(2).fill(`/api/web/v1/communications/v1/support/auction-results/${id(2)}/message-attempts/${attempt}/check`));
});

it.each([401,403])('allows the same open after access returns and a fresh read confirms no conversation after %s',async status=>{
  const refetch=vi.fn().mockResolvedValue({isSuccess:false,error:unopened});
  state.read.mockReturnValue({isError:true,isFetchedAfterMount:true,error:unopened,refetch});
  state.request.mockRejectedValueOnce(new ApiError(status,'denied',''));
  await click('Open support conversation');
  expect(draw().some(node=>node.type===Button&&node.props.children==='Open support conversation')).toBe(false);
  await click('Try again');
  state.request.mockResolvedValueOnce(conversation);
  await click('Open support conversation');
  expect(state.request).toHaveBeenCalledTimes(2);
  expect(state.request.mock.calls[1][1].headers).toEqual(state.request.mock.calls[0][1].headers);
});
