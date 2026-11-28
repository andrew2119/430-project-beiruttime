import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {Children,isValidElement,type ReactElement} from 'react';
import {Button,Input} from '@beirut-time/ui/foundation';
import type {MaximumQuote} from './maximum-api';
import {readPendingMaximum,retainPendingMaximum,retainPendingReview,settlePendingMaximum} from './pending-maximum';
import {ApiError} from '@/lib/api/client';
import {BuyerAuctionView,LegacyMaximumReceipt,MaximumForm} from './proxy-bid';
const language=vi.hoisted(()=>({current:'en' as 'en'|'ar'}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>language.current,useLocaleChange:()=>vi.fn()}));
const source=vi.hoisted(()=>({current:{} as Record<string,unknown>}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>source.current}));
vi.mock('@tanstack/react-query',()=>({useQuery:()=>source.current}));
const hooks=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,effects:[] as (()=>unknown)[]}));
const api=vi.hoisted(()=>({readOwnMaximum:vi.fn(),lookupMaximum:vi.fn(),lookupMaximumV1:vi.fn(),sendMaximum:vi.fn(),recoverLegacyMaximum:vi.fn(),reviewMaximum:vi.fn(),restoreMaximumIntent:vi.fn(),restoreMaximumReview:vi.fn()}));
vi.mock('./maximum-api',async()=>({...await vi.importActual('./maximum-api'),...api}));
const identity=vi.hoisted(()=>({state:'authenticated',signedIn:true,subjectId:'buyer-a',fingerprint:'access-a' as string|null,roles:['buyer'],organizationId:null}));
vi.mock('./session',()=>({useBuyerSession:()=>identity}));
vi.mock('react',async()=>({...await vi.importActual('react'),useEffectEvent:(handler:()=>void)=>handler,useEffect:(effect:()=>unknown,deps:unknown[])=>{const at=hooks.cursor++;const old=hooks.slots[at] as unknown[]|undefined;if(!old||deps.some((value,i)=>value!==old[i])){hooks.slots[at]=deps;hooks.effects.push(effect);}},useRef:(initial:unknown)=>{const at=hooks.cursor++;if(!(at in hooks.slots))hooks.slots[at]={current:initial};return hooks.slots[at];},useState:(initial:unknown)=>{const at=hooks.cursor++;if(!(at in hooks.slots))hooks.slots[at]=initial;return [hooks.slots[at],(value:unknown)=>{hooks.slots[at]=typeof value==='function'?value(hooks.slots[at]):value;}];}}));
type Node=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Node[]{if(!isValidElement(value))return [];const node=value as Node;return [node,...Children.toArray(node.props.children as never).flatMap(nodes)];}
const quote={auction_revision:3,amount_minor:450000,buyer_fee_minor:13500,total_minor:463500,currency:'USD',fee_quote_id:'quote-a',quote_revision:1,policy_revision:'2',binding:{schedule_id:'usd-v2'},expires_at:'2099-01-01T00:00:00Z'};
const getQuote=vi.fn<NonNullable<Parameters<typeof MaximumForm>[0]['getQuote']>>(async()=>quote as MaximumQuote);
const retainAuction=vi.fn();
function draw(lifecycle:'live'|'ended'|'unavailable'|'replaced'|'held'='live',locale:'en'|'ar'='en',revision=3) {
  hooks.cursor=0;
  const boundary=MaximumForm({auctionId:'auction-a',revision,currency:'USD',locale,lifecycle,onRefresh:()=>{},onRecoveryChange:retainAuction,getQuote});
  return (boundary.type as (props:unknown)=>Node)(boundary.props);
}
async function effects(){for(const effect of hooks.effects.splice(0))effect();await Promise.resolve();await Promise.resolve();}
async function submit(){const form=nodes(draw()).find(node=>node.type==='form')!;await effects();(form.props.onSubmit as (event:unknown)=>void)({preventDefault(){}});await Promise.resolve();await Promise.resolve();await Promise.resolve();}
beforeEach(()=>{
  const pending=typeof localStorage==='undefined'?null:readPendingMaximum('auction-a','access-a','buyer-a');
  if(pending) settlePendingMaximum('auction-a',pending.intent,pending.review?'review':'bid');
  identity.state='authenticated';identity.fingerprint='access-a';vi.useFakeTimers();hooks.slots=[];hooks.effects=[];vi.clearAllMocks();vi.stubGlobal('navigator',{onLine:true});const records=new Map<string,string>();vi.stubGlobal('localStorage',{
  get length(){return records.size;},key:(index:number)=>[...records.keys()][index]??null,
  getItem:(key:string)=>records.get(key)??null,setItem:(key:string,value:string)=>records.set(key,value),removeItem:(key:string)=>records.delete(key),
});vi.stubGlobal('sessionStorage',{getItem:()=>null,removeItem:()=>{}});api.readOwnMaximum.mockResolvedValue({revision:3,amount_minor:null,active:false,watch_id:'watch-a'});api.reviewMaximum.mockResolvedValue(undefined);api.sendMaximum.mockResolvedValue({state:'pending'});});
it('a returned older revision never enables preview or submission',async()=>{
  api.readOwnMaximum.mockResolvedValue({revision:2,amount_minor:450000,active:true});draw();await effects();
  expect(nodes(draw()).find(node=>node.type===Input)?.props.disabled).toBe(true);
  await submit();expect(getQuote).not.toHaveBeenCalled();expect(api.sendMaximum).not.toHaveBeenCalled();
});
it('keeps an uncertain reference through close and language change, then checks that receipt',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();api.sendMaximum.mockRejectedValue(new Error('response_lost'));await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  const ended=draw('ended','ar');expect(nodes(ended).some(node=>node.type==='form')).toBe(false);
  expect(JSON.stringify(ended)).toContain(pending.key);
  api.lookupMaximum.mockResolvedValueOnce({state:'pending'}).mockResolvedValueOnce({state:'accepted'});
  const check=()=>nodes(draw('ended','ar')).find(node=>node.type===Button&&node.props.onClick)!;
  await (check().props.onClick as ()=>Promise<void>)();await Promise.resolve();await Promise.resolve();
  expect(JSON.stringify(draw('ended'))).toContain(pending.key);
  await (check().props.onClick as ()=>Promise<void>)();await Promise.resolve();await Promise.resolve();
  expect(api.lookupMaximum.mock.calls[0].slice(0,2)).toEqual(['auction-a',pending]);
  expect(api.lookupMaximum.mock.calls[1][1]).toBe(pending);expect(api.sendMaximum).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(draw('ended'))).toContain('Maximum accepted');
  expect(JSON.stringify(draw('ended'))).toContain(pending.key);
  await recoverBid(draw('ended'),'Continue to the current auction');
  expect(JSON.stringify(draw('ended'))).not.toContain(pending.key);
});

it('settles a missing original bid only after its bound same-key denial is returned',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('response_lost'));
  await submit();
  const original=api.sendMaximum.mock.calls[0][1];
  api.lookupMaximum.mockRejectedValueOnce(new ApiError(404,'not_found',''));
  await recoverBid(draw(),'Check request status');
  expect(JSON.stringify(draw())).toContain(original.key);
  api.sendMaximum.mockResolvedValueOnce({state:'denied'});
  await recoverBid(draw(),'Retry original bid');
  expect(api.sendMaximum.mock.calls[1][1]).toBe(original);
  expect(readPendingMaximum('auction-a','access-a','buyer-a')).toBeNull();
  expect(JSON.stringify(draw())).toContain('Bid not accepted');
  expect(JSON.stringify(draw())).toContain(original.key);
  expect(nodes(draw()).some(node=>node.props.children==='Retry original bid')).toBe(false);
});

it.each([401,403])('clears private content on receipt denial %s and hides recovery until a current read restores access',async status=>{
  api.readOwnMaximum.mockResolvedValue({revision:3,amount_minor:440000,active:true,watch_id:'watch-a'});
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();api.sendMaximum.mockRejectedValue(new Error('response_lost'));await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  api.lookupMaximum.mockRejectedValueOnce(new ApiError(status,'denied',''));
  const check=nodes(draw()).find(node=>node.type===Button&&node.props.onClick)!;
  await (check.props.onClick as ()=>Promise<void>)();await Promise.resolve();await Promise.resolve();
  for(const locale of ['en','ar'] as const) {
    const denied=draw('live',locale);
    expect(nodes(denied).some(node=>node.type===Input)).toBe(false);
    expect(JSON.stringify(denied)).not.toContain('440000');
    expect(JSON.stringify(denied)).not.toContain('proxy-quote');
    expect(JSON.stringify(denied)).not.toContain(pending.key);
  }
  await submit();expect(api.sendMaximum).toHaveBeenCalledTimes(1);expect(getQuote).toHaveBeenCalledTimes(1);
  api.lookupMaximum.mockResolvedValueOnce({state:'accepted'});
  expect(nodes(draw()).some(node=>node.props.children==='Check request status')).toBe(false);
  expect(api.lookupMaximum).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(5000);
  expect(JSON.stringify(draw())).toContain(pending.key);
  await recoverBid(draw(),'Check request status');
  expect(api.lookupMaximum.mock.calls[1][1]).toBe(pending);
  expect(JSON.stringify(draw())).toContain('Maximum accepted');
  await recoverBid(draw(),'Continue to the current auction');
  expect(JSON.stringify(draw())).not.toContain(pending.key);
});

it.each([401,403])('clears private content on preview denial %s',async status=>{
  api.readOwnMaximum.mockResolvedValue({revision:3,amount_minor:440000,active:true,watch_id:'watch-a'});
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  getQuote.mockRejectedValueOnce(new ApiError(status,'denied',''));
  await submit();
  for(const locale of ['en','ar'] as const) {
    const denied=draw('live',locale);
    expect(nodes(denied).some(node=>node.type===Input)).toBe(false);
    expect(JSON.stringify(denied)).not.toContain('440000');
  }
  await submit();expect(getQuote).toHaveBeenCalledTimes(1);expect(api.sendMaximum).not.toHaveBeenCalled();
});

it.each(['review','submit'] as const)('clears private content on %s access denial and preserves the reference',async stage=>{
  api.readOwnMaximum.mockResolvedValue({revision:3,amount_minor:440000,active:true,watch_id:'watch-a'});
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  if(stage==='review') api.reviewMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  else api.sendMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  await submit();
  const pending=(stage==='submit'?api.sendMaximum.mock.calls[0][1].key:undefined);
  for(const locale of ['en','ar'] as const) {
    const denied=draw('live',locale);
    expect(nodes(denied).some(node=>node.type===Input)).toBe(false);
    expect(JSON.stringify(denied)).not.toContain('440000');
    expect(JSON.stringify(denied)).not.toContain('proxy-quote');
    if(pending) expect(JSON.stringify(denied)).not.toContain(pending);
  }
  await submit();expect(getQuote).toHaveBeenCalledTimes(1);
  expect(api.sendMaximum).toHaveBeenCalledTimes(stage==='submit'?1:0);
});

it.each([{}, {items:[]}, {items:[{id:'invalid'}]}, {missingThreshold:true}, {overlong:true}, {contradictory:true}, {heldMode:'first_bid_pending'}, {heldMode:'listing_edit_pending'}])('keeps the form boundary mounted across a hold or invalid source %j',data=>{
  const auction={id:'00000000-0000-4000-8000-000000000006',listing_id:'listing-a',currency:'USD',revision:3,status:'live',mode:'bidding',
    current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],high_value_minor:1000000,accepted_sequence:1,opening_minor:400000,leader:'Bidder 1a2b3c4d',
    starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',server_time:'2030-01-01T12:00:00Z'};
  const refetch=vi.fn();
  function slot() {
    hooks.cursor=0;
    const view=BuyerAuctionView({locale:'en',listingId:'listing-a'});
    const slot=Children.toArray(view.props.children)[1] as Node;
    const content=(slot.type as (props:unknown)=>Node)(slot.props);
    const arrival=(content.type as (props:unknown)=>Node)(content.props);
    return Children.only(arrival.props.children) as Node;
  }
  source.current={data:{items:[auction]},isSuccess:true,refetch};
  const first=slot();
  expect(first.type).toBe(MaximumForm);
  const refresh='missingThreshold' in data?{items:[{...auction,high_value_minor:undefined}]}:
    'overlong' in data?{items:[{...auction,ends_at:'2030-04-01T00:00:00.001Z'}]}:
    'contradictory' in data?{items:[{...auction,current_minor:390000,leader:null}]}:
    'heldMode' in data?{items:[{...auction,mode:data.heldMode}]}:data;
  source.current={data:refresh,isSuccess:true,refetch};
  const missing=slot();
  expect(missing.type).toBe(first.type);
  expect(missing.key).toBe(first.key);
  expect(missing.props.auctionId).toBe(first.props.auctionId);
  expect(missing.props.lifecycle).toBe('heldMode' in data?'held':'unavailable');
  source.current={data:{items:[auction]},isSuccess:true,refetch};
  expect(slot().props.lifecycle).toBe('live');
});

it.each(['unavailable','held'] as const)('keeps receipt recovery available while %s without admitting a new bid',async lifecycle=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();api.sendMaximum.mockRejectedValue(new Error('response_lost'));await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  const unavailable=draw(lifecycle,'ar');
  expect(nodes(unavailable).some(node=>node.type==='form')).toBe(false);
  expect(JSON.stringify(unavailable)).toContain(pending.key);
  api.lookupMaximum.mockResolvedValueOnce({state:'accepted'});
  const check=nodes(unavailable).find(node=>node.type===Button&&node.props.onClick&&node.props.variant!=='outline')!;
  await (check.props.onClick as ()=>Promise<void>)();await Promise.resolve();await Promise.resolve();
  expect(api.lookupMaximum.mock.calls[0][1]).toBe(pending);
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});

it('recovers from fee review denial with a fresh preview and no nonexistent receipt lookup',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();api.reviewMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));await submit();
  expect(api.sendMaximum).not.toHaveBeenCalled();expect(api.lookupMaximum).not.toHaveBeenCalled();
  expect(JSON.stringify(draw())).not.toContain('Request reference');
  const retry=nodes(draw()).find(node=>node.type===Button&&node.props.variant==='outline')!;
  (retry.props.onClick as ()=>void)();draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();await submit();expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});
it.each(['leading','outbid'] as const)('shows %s standing separately from an inactive ceiling, including after close',async standing=>{
  api.readOwnMaximum.mockResolvedValue({revision:3,amount_minor:440000,active:false,watch_id:'watch-a',standing});
  draw();await effects();
  for(const locale of ['en','ar'] as const) {
    const live=draw('live',locale);
    const ended=draw('ended',locale);
    const inactive=locale==='en'?'Inactive ceiling':'سقف غير نشط';
    expect(JSON.stringify(live)).toContain(inactive);
    expect(JSON.stringify(ended)).toContain(inactive);
    const label=standing==='leading'
      ? (locale==='en'?'You are leading':'أنت المتصدر')
      : (locale==='en'?'You have been outbid':'تم تجاوز مزايدتك');
    expect(JSON.stringify(live)).toContain(label);
    expect(JSON.stringify(ended)).toContain(label);
    expect(JSON.stringify(ended)).toContain(locale==='en'?'Your stored ceiling':'سقفك المحفوظ');
    expect(nodes(ended).some(node=>node.type==='form')).toBe(false);
  }
});
it('retries uncertain fee review with the same review reference before submitting the bid',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));await submit();
  const reference=api.reviewMaximum.mock.calls[0][1];
  expect(api.sendMaximum).not.toHaveBeenCalled();
  await submit();
  expect(api.reviewMaximum.mock.calls[1][1]).toBe(reference);
  expect(api.lookupMaximum).not.toHaveBeenCalled();expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});

it.each(['live','ended','unavailable','replaced'] as const)('retains the recovered fee review during %s without submitting a bid',async lifecycle=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));await submit();
  const reference=api.reviewMaximum.mock.calls[0][1];
  for(const locale of ['en','ar'] as const) {
    const pending=draw(lifecycle,locale);
    expect(JSON.stringify(pending)).toContain(reference);
    expect(nodes(pending).some(node=>node.type==='form')).toBe(lifecycle==='live');
  }
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  async function recover() {
    const button=nodes(draw(lifecycle)).find(node=>node.type===Button&&node.props.children==='Recover fee review')!;
    (button.props.onClick as ()=>void)();await Promise.resolve();await Promise.resolve();
  }
  await recover();expect(JSON.stringify(draw(lifecycle,'ar'))).toContain(reference);
  await recover();
  expect(api.reviewMaximum.mock.calls.map(call=>call[1])).toEqual([reference,reference,reference]);
  expect(api.sendMaximum).not.toHaveBeenCalled();expect(api.lookupMaximum).not.toHaveBeenCalled();
  for(const locale of ['en','ar'] as const) {
    const receipt=JSON.stringify(draw(lifecycle,locale));
    expect(receipt).toContain(reference);
    expect(receipt).toContain('auction-a');
    expect(receipt).toContain(locale==='en'?'Fee review confirmed. No bid was sent.':'تأكدت مراجعة الرسوم. لم تُرسل أي مزايدة.');
  }
  await recoverBid(draw(lifecycle),lifecycle==='replaced'?'Continue to the current auction':'Dismiss receipt');
  expect(JSON.stringify(draw(lifecycle))).not.toContain(reference);
});


it('follows the mounted detail language while retaining input, fee review and bid references',async()=>{
  function detail(locale:'en'|'ar') {
    language.current=locale;
    const view=BuyerAuctionView({locale:'en',listingId:'listing-a'});
    const children=Children.toArray(view.props.children);
    const slot=children[1] as Node;
    const header=children[0] as Node;
    expect(header.props.title).toBe(locale==='ar'?'المزايدة في المزاد':'Auction bidding');
    return slot.props.locale as 'en'|'ar';
  }
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  expect(nodes(draw('live',detail('ar'))).find(node=>node.type===Input)!.props.value).toBe('4500');
  await submit();
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));await submit();
  const reference=api.reviewMaximum.mock.calls[0][1];
  expect(JSON.stringify(draw('live',detail('en')))).toContain(reference);
  expect(JSON.stringify(draw('live',detail('ar')))).toContain(reference);
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'));await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  expect(JSON.stringify(draw('ended',detail('en')))).toContain(pending.key);
  expect(JSON.stringify(draw('ended',detail('ar')))).toContain(pending.key);
  expect(api.reviewMaximum.mock.calls[1][1]).toBe(reference);
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});

afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});

it('clears the ceiling after current access is revoked at the same auction revision',async()=>{
  api.readOwnMaximum.mockResolvedValueOnce({revision:3,amount_minor:440000,active:true,watch_id:'watch-a'})
    .mockRejectedValueOnce(new ApiError(403,'denied',''));
  draw();await effects();
  expect(JSON.stringify(draw())).toContain('Your stored ceiling');
  await vi.advanceTimersByTimeAsync(5000);
  expect(api.readOwnMaximum).toHaveBeenCalledTimes(2);
  expect(JSON.stringify(draw())).not.toContain('Your stored ceiling');
  expect(nodes(draw()).some(node=>node.type===Input)).toBe(false);
  await submit();
  expect(getQuote).not.toHaveBeenCalled();
});

it('hides a retained private ceiling when a same-revision recheck times out',async()=>{
  api.readOwnMaximum.mockResolvedValueOnce({revision:3,amount_minor:440000,active:true,watch_id:'watch-a'})
    .mockImplementationOnce(()=>new Promise(()=>{}));
  draw();await effects();
  expect(JSON.stringify(draw())).toContain('Your stored ceiling');
  await vi.advanceTimersByTimeAsync(8000);
  expect(JSON.stringify(draw())).toContain('Stored ceiling unavailable');
  expect(JSON.stringify(draw())).not.toContain('Your stored ceiling');
  expect(nodes(draw()).find(node=>node.type===Input)?.props.disabled).toBe(true);
});

it.each([
  ['quote_expired', 'The preview expired'],
  ['quote_binding_mismatch', 'The auction changed'],
])('clears a terminal fee review %s and allows a fresh preview',async(code,message)=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const reference=api.reviewMaximum.mock.calls[0][1];
  api.reviewMaximum.mockRejectedValueOnce(new ApiError(409,code,''));
  const recover=nodes(draw()).find(node=>node.type===Button&&node.props.children==='Recover fee review')!;
  (recover.props.onClick as ()=>void)();
  await Promise.resolve();await Promise.resolve();
  expect(api.reviewMaximum.mock.calls[1][1]).toBe(reference);
  expect(JSON.stringify(draw())).toContain(message);
  expect(JSON.stringify(draw())).not.toContain(reference);
  expect(api.sendMaximum).not.toHaveBeenCalled();
  await submit();
  expect(getQuote).toHaveBeenCalledTimes(2);
});

it('keeps a pending original auction mounted when the same listing is relisted',()=>{
  const original={id:'00000000-0000-4000-8000-000000000006',listing_id:'listing-a',currency:'USD',revision:3,status:'live',mode:'bidding',
    current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],high_value_minor:1000000,accepted_sequence:1,opening_minor:400000,leader:'Bidder 1a2b3c4d',
    starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',server_time:'2030-01-01T12:00:00Z'};
  const replacement={...original,id:'00000000-0000-4000-8000-000000000007'};
  function slot(auction:typeof original) {
    hooks.cursor=0;
    source.current={data:{items:[auction]},isSuccess:true,refetch:vi.fn()};
    const view=BuyerAuctionView({locale:'en',listingId:original.listing_id});
    const slot=Children.toArray(view.props.children)[1] as Node;
    const content=(slot.type as (props:unknown)=>Node)(slot.props);
    const arrival=(content.type as (props:unknown)=>Node)(content.props);
    return Children.only(arrival.props.children) as Node;
  }
  const before=slot(original);
  (before.props.onRecoveryChange as (pending:boolean)=>void)(true);
  const after=slot(replacement);
  expect(after.props.auctionId).toBe(original.id);
  expect(after.props.lifecycle).toBe('replaced');
  expect(after.key).toBe(before.key);
  (after.props.onRecoveryChange as (pending:boolean)=>void)(false);
  expect(slot(replacement).props.auctionId).toBe(replacement.id);
});

it.each(['en','ar'] as const)('keeps a selected auction independent of another pending auction in %s',async locale=>{
  const listingId='listing-a';
  const selected='00000000-0000-4000-8000-000000000006';
  const earlier='00000000-0000-4000-8000-000000000007';
  const original={
    key:'test-earlier-bid',actor_id:'buyer-a',owner:'access-a',watch_id:'watch-a',
    fee_quote_id:'test-earlier-quote',revision:3,quote_revision:1,policy_revision:'test-policy',amount_minor:450000,
  };
  expect(retainPendingReview(listingId,earlier,original,{key:'test-earlier-review'})).toBe(true);
  expect(retainPendingMaximum(listingId,earlier,original)).toBe(true);
  const auction={
    id:selected,listing_id:listingId,currency:'USD',revision:4,status:'live',mode:'bidding',
    current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],
    high_value_minor:1000000,accepted_sequence:1,opening_minor:400000,leader:'Bidder 1a2b3c4d',
    starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',server_time:'2030-01-01T12:00:00Z',
  };
  function drawSelected() {
    hooks.cursor=0;
    const view=BuyerAuctionView({locale,listingId,auctionId:selected});
    const slot=Children.toArray(view.props.children)[1] as Node;
    const content=(slot.type as (props:unknown)=>Node)(slot.props);
    return (content.type as (props:unknown)=>Node)(content.props);
  }
  language.current=locale;
  try {
    source.current={data:{items:[auction]},isSuccess:true,refetch:vi.fn()};
    drawSelected();await effects();
    const forms=nodes(drawSelected()).filter(node=>node.type===MaximumForm);
    expect(forms.map(form=>[form.props.auctionId,form.props.lifecycle])).toEqual([
      [selected,'live'],[earlier,'other-auction'],
    ]);
    expect(forms[0].props.snapshot).toBe(auction);
    expect(forms[1].props.snapshot).toBeUndefined();
    source.current={data:undefined,isError:true,refetch:vi.fn()};
    const duringOutage=nodes(drawSelected()).filter(node=>node.type===MaximumForm);
    expect(duringOutage[0].props.auctionId).toBe(selected);
    expect(duringOutage[0].props.lifecycle).toBe('unavailable');
    expect(duringOutage[1].props.auctionId).toBe(earlier);
    expect(duringOutage[1].key).toBe(forms[1].key);
    expect(readPendingMaximum(listingId,'access-a','buyer-a',id=>id===selected)).toBeNull();
    expect(readPendingMaximum(listingId,'access-a','buyer-a',id=>id===earlier)?.intent).toEqual(original);
  } finally {
    language.current='en';
  }
});

it.each([
  ['empty',{data:{items:[]},isSuccess:true}],
  ['invalid',{data:{items:[{id:'invalid'}]},isSuccess:true}],
  ['unavailable',{isError:true}],
] as const)('recovers a reopened selected auction when the public snapshot is %s',async (_state,publicRead)=>{
  const listingId='listing-a';
  const auctionId='00000000-0000-4000-8000-000000000006';
  const original={
    key:'test-selected-bid',actor_id:'buyer-a',owner:'access-a',watch_id:'watch-a',
    fee_quote_id:'test-selected-quote',revision:3,quote_revision:1,
    policy_revision:'test-policy',amount_minor:450000,
  };
  expect(retainPendingReview(listingId,auctionId,original,{key:'test-selected-review'})).toBe(true);
  expect(retainPendingMaximum(listingId,auctionId,original)).toBe(true);
  const storageKey=localStorage.key(0)!;
  const saved=localStorage.getItem(storageKey)!;
  settlePendingMaximum(listingId,original,'bid');
  localStorage.setItem(storageKey,saved);

  function drawSelected() {
    hooks.cursor=0;
    const view=BuyerAuctionView({locale:'en',listingId,auctionId});
    const slot=Children.toArray(view.props.children)[1] as Node;
    const content=(slot.type as (props:unknown)=>Node)(slot.props);
    const panel=(content.type as (props:unknown)=>Node)(content.props);
    const form=nodes(panel).find(node=>node.type===MaximumForm);
    if(!form) return panel;
    const boundary=MaximumForm(form.props as Parameters<typeof MaximumForm>[0]);
    return (boundary.type as (props:unknown)=>Node)(boundary.props);
  }

  source.current={...publicRead,refetch:vi.fn()};
  expect(JSON.stringify(drawSelected())).not.toContain(original.key);
  await effects();
  api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  expect(JSON.stringify(drawSelected())).not.toContain(original.key);
  await effects();
  expect(JSON.stringify(drawSelected())).toContain('Your current account cannot use buyer actions.');
  expect(JSON.stringify(drawSelected())).not.toContain(original.key);
  expect(api.lookupMaximum).not.toHaveBeenCalled();

  api.readOwnMaximum.mockResolvedValue({revision:4,amount_minor:null,active:false,watch_id:original.watch_id});
  await vi.advanceTimersByTimeAsync(5000);
  const authorized=drawSelected();
  expect(JSON.stringify(authorized)).toContain(original.key);
  expect(JSON.stringify(authorized)).not.toContain('Review maximum and fees');
  api.lookupMaximum.mockResolvedValueOnce({state:'accepted'});
  await recoverBid(authorized,'Check request status');
  expect(api.lookupMaximum.mock.calls[0].slice(0,2)).toEqual([auctionId,{...JSON.parse(saved).intent,owner:original.owner}]);
  expect(api.sendMaximum).not.toHaveBeenCalled();
  expect(localStorage.getItem(storageKey)).toBeNull();
  expect(JSON.stringify(drawSelected())).toContain('Maximum accepted');
});

it('retains the original bid after a lost response and a retry returning 404',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'))
    .mockRejectedValueOnce(new ApiError(404,'http_error',''));
  await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  await recoverBid(draw(),'Retry original bid');
  expect(api.sendMaximum.mock.calls[1][1]).toBe(pending);
  expect(JSON.stringify(draw())).toContain(pending.key);
  expect(JSON.stringify(draw())).not.toContain('Maximum accepted');
});

it('reuses an uncertain preview reference across language changes and replaces it for a changed amount',async()=>{
  draw();await effects();
  function change(amount:string) {
    (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)(amount);
  }
  change('4500');
  getQuote.mockRejectedValueOnce(new Error('test-response-lost'))
    .mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  draw('live','ar');
  await submit();
  change('4600');
  await submit();
  expect(getQuote.mock.calls.map(call=>call[0])).toEqual([450000,450000,460000]);
  expect(getQuote.mock.calls[1][2]).toBe(getQuote.mock.calls[0][2]);
  expect(getQuote.mock.calls[2][2]).not.toBe(getQuote.mock.calls[0][2]);
});


async function recoverBid(panel:Node,label:string) {
  const button=nodes(panel).find(node=>node.type===Button&&node.props.children===label)!;
  (button.props.onClick as ()=>void)();
  await Promise.resolve();await Promise.resolve();
}

it('keeps the detail recovery boundary through a temporary identity outage',()=>{
  const key=()=>{
    const view=BuyerAuctionView({locale:'en',listingId:'listing-a'});
    const slot=Children.toArray(view.props.children)[1] as Node;
    return (slot.type as (props:unknown)=>Node)(slot.props).key;
  };
  const authenticated=key();
  identity.state='unavailable';
  expect(key()).toBe(authenticated);
  identity.state='authenticated';
  expect(key()).toBe(authenticated);
  identity.fingerprint='access-b';
  expect(key()).not.toBe(authenticated);
});

it.each([
  ['live',4,'stale'],
  ['ended',3,'accepted'],
  ['replaced',3,'denied'],
] as const)('recovers the original bid during %s at revision %i',async(lifecycle,revision,state)=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  api.readOwnMaximum.mockResolvedValue({revision:revision+1,amount_minor:null,active:false,watch_id:'watch-a'});
  draw(lifecycle,'en',revision);await effects();
  if(revision===3) await vi.advanceTimersByTimeAsync(5000);
  api.lookupMaximum.mockRejectedValueOnce(new ApiError(404,'operation_not_found',''));
  await recoverBid(draw(lifecycle,'en',revision),'Check request status');
  expect(JSON.stringify(draw(lifecycle,'en',revision))).toContain(pending.key);
  api.sendMaximum.mockResolvedValueOnce({state});
  await recoverBid(draw(lifecycle,'en',revision),'Retry original bid');
  expect(api.sendMaximum.mock.calls[1].slice(0,2)).toEqual(['auction-a',pending]);
  expect(api.sendMaximum.mock.calls[1][1]).toBe(pending);
  const receipt=JSON.stringify(draw(lifecycle,'en',revision));
  expect(receipt).toContain('Auction for this receipt');
  expect(receipt).toContain('auction-a');
  expect(receipt).toContain(pending.key);
  expect(receipt).toContain({accepted:'Maximum accepted',denied:'Bid not accepted',stale:'The auction changed'}[state]);
  await recoverBid(draw(lifecycle,'en',revision),'Continue to the current auction');
  expect(JSON.stringify(draw(lifecycle,'en',revision))).not.toContain(pending.key);
});

it.each(['allowed','denied','timeout'] as const)('waits for a current auction access check after identity restoration (%s)',async outcome=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const pending=api.sendMaximum.mock.calls[0][1];
  identity.state='unavailable';
  expect(JSON.stringify(draw())).not.toContain(pending.key);
  await effects();
  identity.state='authenticated';
  api.readOwnMaximum.mockImplementationOnce(()=>new Promise((resolve,reject)=>{
    if(outcome==='allowed') {
      setTimeout(()=>setTimeout(()=>resolve({revision:3,amount_minor:null,active:false,watch_id:'watch-a'}),400),250);
    }
    if(outcome==='denied') setTimeout(()=>reject(new ApiError(403,'denied','')),100);
  }));
  function expectHidden() {
    for(const locale of ['en','ar'] as const) {
      const panel=draw('live',locale);
      expect(JSON.stringify(panel)).not.toContain(pending.key);
      expect(nodes(panel).some(node=>node.props.children===(locale==='en'?'Check request status':'التحقق من حالة الطلب')||
        node.props.children===(locale==='en'?'Retry original bid':'إعادة إرسال المزايدة الأصلية'))).toBe(false);
    }
    expect(api.lookupMaximum).not.toHaveBeenCalled();
    expect(api.sendMaximum).toHaveBeenCalledTimes(1);
  }
  expectHidden();
  await effects();
  expectHidden();
  if(outcome==='allowed') {
    await vi.advanceTimersByTimeAsync(600);
    expectHidden();
    await vi.advanceTimersByTimeAsync(50);
  } else {
    await vi.advanceTimersByTimeAsync(outcome==='timeout'?3000:100);
  }
  if(outcome!=='allowed') {
    expectHidden();
    expect(JSON.stringify(draw())).toContain(outcome==='timeout'?'Stored ceiling unavailable':'Your current account cannot use buyer actions.');
    await vi.advanceTimersByTimeAsync(5000);
  }
  expect(JSON.stringify(draw('live','ar'))).toContain(pending.key);
  api.lookupMaximum.mockResolvedValueOnce({state:'pending'});
  await recoverBid(draw(),'Check request status');
  expect(api.lookupMaximum.mock.calls[0][1]).toBe(pending);
  api.sendMaximum.mockResolvedValueOnce({state:'accepted'});
  await recoverBid(draw(),'Retry original bid');
  expect(api.sendMaximum.mock.calls[1]).toEqual(['auction-a',pending,expect.any(AbortSignal)]);
});

it.each([
  ['ended',409,'already_reviewed'],
  ['replaced',409,'idempotency_conflict'],
  ['replaced',404,'review_denied'],
  ['replaced',422,'validation_error'],
] as const)('resolves a fee review refused after %s with status %i (%s)',async(lifecycle,status,code)=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const reference=api.reviewMaximum.mock.calls[0][1];
  api.reviewMaximum.mockRejectedValueOnce(new ApiError(status,code,''));
  await recoverBid(draw(lifecycle),'Recover fee review');
  const resolved=draw(lifecycle);
  expect(JSON.stringify(resolved)).not.toContain(reference);
  expect(nodes(resolved).some(node=>node.props.children==='Recover fee review')).toBe(false);
  expect(api.reviewMaximum.mock.calls[1][1]).toBe(reference);
  expect(api.sendMaximum).not.toHaveBeenCalled();
  expect(api.lookupMaximum).not.toHaveBeenCalled();
});

vi.mock('@/shell/foundation/path',async importOriginal=>({
  ...await importOriginal<typeof import('@/shell/foundation/path')>(),usesFoundationShell:()=>true,
}));

it.each([404,503])('blocks new bids when the v2 authority returns %s',async status=>{
  api.readOwnMaximum.mockRejectedValue(new ApiError(status,'unavailable',''));
  draw();await effects();
  const panel=draw();
  expect(JSON.stringify(panel)).toContain('Stored ceiling unavailable');
  expect(nodes(panel).find(node=>node.type===Input)?.props.disabled).toBe(true);
  await submit();
  expect(getQuote).not.toHaveBeenCalled();
  expect(api.sendMaximum).not.toHaveBeenCalled();
});


it('labels the same reviewed fee as simulated in both languages',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  expect(JSON.stringify(draw('live','en'))).toContain('Simulated fee preview. The buyer fee is 3%');
  expect(JSON.stringify(draw('live','ar'))).toContain('معاينة رسوم محاكاة. تُضاف رسوم المشتري بنسبة ٣٪');
  expect(getQuote).toHaveBeenCalledTimes(1);
  expect(api.sendMaximum).not.toHaveBeenCalled();
});

it('sends a reviewed command even when the browser clock is past the preview expiry',async()=>{
  vi.setSystemTime(new Date('2100-01-01T00:00:00Z'));
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  await submit();
  expect(api.reviewMaximum).toHaveBeenCalledTimes(1);
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});


it('reviews the exact pasted amount and rejects digits beyond the supported length',async()=>{
  draw();await effects();
  const change=(value:string)=>(nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)(value);
  change(' '.repeat(12)+'4500.99');
  await submit();
  expect(getQuote).toHaveBeenCalledWith(450099,expect.any(AbortSignal),expect.any(String));
  change('1234567890123456789');
  expect(JSON.stringify(draw())).toContain('Enter a positive amount');
  await submit();
  expect(getQuote).toHaveBeenCalledTimes(1);
});

it.each(['allowed','denied','timeout'] as const)('hides a typed amount until restored record access is verified (%s)',async outcome=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500.99');
  expect(nodes(draw()).find(node=>node.type===Input)?.props.value).toBe('4500.99');

  identity.state='unavailable';
  expect(nodes(draw()).find(node=>node.type===Input)).toBeUndefined();
  await effects();
  identity.state='authenticated';
  api.readOwnMaximum.mockImplementationOnce(()=>new Promise((resolve,reject)=>{
    if(outcome==='allowed') setTimeout(()=>resolve({revision:3,amount_minor:null,active:false,watch_id:'watch-a'}),100);
    if(outcome==='denied') setTimeout(()=>reject(new ApiError(403,'denied','')),100);
  }));
  expect(nodes(draw()).find(node=>node.type===Input)?.props.value).toBe('');
  await effects();
  expect(nodes(draw('live','ar')).find(node=>node.type===Input)?.props.value).toBe('');
  await vi.advanceTimersByTimeAsync(outcome==='timeout'?3000:100);
  const input=nodes(draw()).find(node=>node.type===Input);
  expect(input?.props.value).toBe(outcome==='allowed'?'4500.99':outcome==='timeout'?'':undefined);
  expect(getQuote).not.toHaveBeenCalled();
});

it.each([{}, {admission:'v1'}])('uses historical access for receipt lookup only (%j)',async legacyFields=>{
  api.readOwnMaximum.mockResolvedValueOnce({schema_version:1,revision:3,...legacyFields});
  draw();await effects();
  const historical=draw();
  expect(nodes(historical).some(node=>node.props.onDenied)).toBe(true);
  expect(nodes(historical).some(node=>node.type===Input)).toBe(false);
  expect(nodes(historical).some(node=>node.type==='form')).toBe(false);
  expect(JSON.stringify(historical)).toContain('New maximum bids are temporarily unavailable');
  expect(getQuote).not.toHaveBeenCalled();
  expect(api.recoverLegacyMaximum).not.toHaveBeenCalled();
  expect(api.sendMaximum).not.toHaveBeenCalled();
});

it.each([403,503])('keeps earlier receipt lookup hidden until the current access read succeeds (%s)',async status=>{
  api.readOwnMaximum.mockRejectedValueOnce(new ApiError(status,'unavailable',''));
  const hasRecovery=()=>nodes(draw()).some(node=>node.props.onDenied);
  expect(hasRecovery()).toBe(false);
  await effects();
  expect(hasRecovery()).toBe(false);
  await vi.advanceTimersByTimeAsync(5000);
  expect(hasRecovery()).toBe(true);
  identity.state='unavailable';
  expect(hasRecovery()).toBe(false);
});

it('keeps a pending v2 reference hidden if only the legacy mode is available',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const reference=api.sendMaximum.mock.calls[0][1].key;
  api.readOwnMaximum.mockResolvedValueOnce({schema_version:1,revision:3});
  await vi.advanceTimersByTimeAsync(5000);
  expect(JSON.stringify(draw())).not.toContain(reference);
  expect(nodes(draw()).some(node=>node.type==='form')).toBe(false);
  expect(api.recoverLegacyMaximum).not.toHaveBeenCalled();
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(5000);
  expect(JSON.stringify(draw())).toContain(reference);
});

it.each(['x','\n'])('does not look up a valid prefix with the extra character %j', async suffix=>{
  const reference='test-'+'a'.repeat(123);
  const render=()=>{
    hooks.cursor=0;
    return nodes(LegacyMaximumReceipt({auctionId:'auction-a',access:'access-a',locale:'en',onDenied:()=>{}}));
  };
  const change=(value:string)=>(render().find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)(value);
  const submit=async()=>{
    const form=render().find(node=>node.type==='form')!;
    (form.props.onSubmit as (event:unknown)=>void)({preventDefault(){}});
    await Promise.resolve();
  };
  for(const [label,value] of [['Your maximum (USD)','4500'],['Original fee quote reference','00000000-0000-4000-8000-000000000004'],['Auction revision','3']]) {
    const field=render().find(node=>node.type===Input&&node.props.label===label)!;
    (field.props.onValueChange as (value:string)=>void)(value);
  }
  change(reference+suffix);
  expect(render().find(node=>node.type===Button)?.props.disabled).toBe(true);
  await submit();
  expect(api.lookupMaximumV1).not.toHaveBeenCalled();
  change(reference);
  api.lookupMaximumV1.mockResolvedValueOnce('accepted');
  await submit();
  expect(api.lookupMaximumV1).toHaveBeenCalledWith('auction-a',reference,{amount_minor:450000,fee_quote_id:'00000000-0000-4000-8000-000000000004',expected_revision:3},'access-a',expect.any(AbortSignal));
});

it.each([401,403])('keeps the preview key after a lost response and access denial %s',async status=>{
  draw();await effects();
  const change=(value:string)=>(nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)(value);
  change('4500');
  getQuote.mockRejectedValueOnce(new Error('test-response-lost'))
    .mockRejectedValueOnce(new ApiError(status,'denied',''));
  await submit();
  await submit();
  expect(nodes(draw()).some(node=>node.type===Input)).toBe(false);
  await submit();
  expect(getQuote).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(5000);
  expect(nodes(draw()).find(node=>node.type===Input)?.props.value).toBe('');
  change('4');
  change('4500');
  await submit();
  expect(getQuote.mock.calls.map(call=>call[0])).toEqual([450000,450000,450000]);
  expect(new Set(getQuote.mock.calls.map(call=>call[2])).size).toBe(1);
  expect(api.sendMaximum).not.toHaveBeenCalled();
});

it.each(['record denial','review replay denial','in-flight review'] as const)(
  'recovers the same fee review after %s and a current access check',async scenario=>{
    draw();await effects();
    (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
    await submit();
    api.reviewMaximum.mockImplementationOnce(async()=>{
      if(scenario==='in-flight review') await new Promise(()=>{});
      throw new Error('test-response-lost');
    });
    await submit();
    const [originalQuote,reference]=api.reviewMaximum.mock.calls[0];

    if(scenario==='review replay denial') {
      api.reviewMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
      await recoverBid(draw(),'Recover fee review');
    } else {
      api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
      await vi.advanceTimersByTimeAsync(5000);
    }

    api.readOwnMaximum.mockImplementationOnce(()=>new Promise(()=>{}));
    await vi.advanceTimersByTimeAsync(8000);
    for(const locale of ['en','ar'] as const) {
      const hidden=draw('ended',locale);
      expect(JSON.stringify(hidden)).not.toContain(reference);
      expect(nodes(hidden).some(node=>node.props.children===(locale==='en'?'Recover fee review':'استعادة مراجعة الرسوم'))).toBe(false);
    }

    await vi.advanceTimersByTimeAsync(5000);
    expect(JSON.stringify(draw('ended','ar'))).toContain(reference);
    await submit();
    expect(getQuote).toHaveBeenCalledTimes(1);
    await recoverBid(draw('ended'),'Recover fee review');
    expect(api.reviewMaximum.mock.lastCall?.slice(0,2)).toEqual([originalQuote,reference]);
    expect(JSON.stringify(draw('ended'))).toContain(reference);
    expect(JSON.stringify(draw('ended'))).toContain('Fee review confirmed. No bid was sent.');
    expect(api.sendMaximum).not.toHaveBeenCalled();
  },
);

it.each(['historical','different watch','denied'] as const)('keeps a terminal receipt private after %s access',async access=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();await submit();
  const reference=api.sendMaximum.mock.calls[0][1].key;
  api.lookupMaximum.mockResolvedValueOnce({state:'accepted'});
  await recoverBid(draw(),'Check request status');
  expect(JSON.stringify(draw())).toContain(reference);

  identity.state='unavailable';
  expect(JSON.stringify(draw())).not.toContain(reference);
  await effects();
  identity.state='authenticated';
  if(access==='denied') api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  else api.readOwnMaximum.mockResolvedValueOnce(access==='historical'?{schema_version:1,revision:3}:
    {schema_version:2,revision:3,amount_minor:null,active:false,watch_id:'other-watch'});
  draw();await effects();
  const hidden=JSON.stringify(draw());
  expect(hidden).not.toContain(reference);
  expect(hidden).not.toContain('Maximum accepted');

  await vi.advanceTimersByTimeAsync(5000);
  expect(JSON.stringify(draw())).toContain(reference);
  await recoverBid(draw(),'Continue to the current auction');
  expect(JSON.stringify(draw())).not.toContain(reference);
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});

it('hides an acceptance that arrives during an identity outage through a delayed record denial',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  let accept!:()=>void;
  api.sendMaximum.mockImplementationOnce(()=>new Promise(resolve=>{
    accept=()=>resolve({state:'accepted'});
  }));
  await submit();

  identity.state='unavailable';
  draw();await effects();
  accept();
  await Promise.resolve();await Promise.resolve();

  identity.state='authenticated';
  api.readOwnMaximum.mockImplementationOnce(()=>new Promise((_,reject)=>{
    setTimeout(()=>reject(new ApiError(403,'denied','')),100);
  }));
  expect(JSON.stringify(draw())).not.toContain('Maximum accepted');
  await effects();
  expect(JSON.stringify(draw())).not.toContain('Maximum accepted');
  await vi.advanceTimersByTimeAsync(100);
  const denied=JSON.stringify(draw());
  expect(denied).toContain('Your current account cannot use buyer actions.');
  expect(denied).not.toContain('Maximum accepted');
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});

it.each([
  ['accepted','Maximum accepted'],
  ['denied','Bid not accepted'],
  ['stale','The auction changed'],
] as const)('retains a direct %s receipt arriving after close until current access is verified',async(state,message)=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  let deliver!:()=>void;
  api.sendMaximum.mockImplementationOnce(()=>new Promise(resolve=>{
    deliver=()=>resolve({state});
  }));
  await submit();
  const operation=api.sendMaximum.mock.calls[0][1];
  api.readOwnMaximum.mockImplementationOnce(()=>new Promise(()=>{}));
  draw('ended','en',4);await effects();
  deliver();await effects();
  expect(JSON.stringify(draw('ended','en',4))).not.toContain(operation.key);
  api.readOwnMaximum.mockResolvedValue({revision:4,amount_minor:null,active:false,watch_id:'watch-a'});
  await vi.advanceTimersByTimeAsync(8000);
  const receipt=JSON.stringify(draw('ended','en',4));
  expect(receipt).toContain(message);
  expect(receipt).toContain(operation.key);
  expect(receipt).toContain('auction-a');
  await recoverBid(draw('ended','en',4),'Continue to the current auction');
  expect(JSON.stringify(draw('ended','en',4))).not.toContain(operation.key);
  expect(api.sendMaximum).toHaveBeenCalledTimes(1);
});

it.each(['live','ended','replaced'] as const)('keeps the original fee review through an ambiguous 404 while %s',async lifecycle=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const original=api.reviewMaximum.mock.calls[0].slice(0,2);
  for(const code of ['http_error','not_found']) {
    api.reviewMaximum.mockRejectedValueOnce(new ApiError(404,code,''));
    await recoverBid(draw(lifecycle),'Recover fee review');
    expect(JSON.stringify(draw(lifecycle,'ar'))).toContain(original[1]);
  }
  await recoverBid(draw(lifecycle),'Recover fee review');
  expect(api.reviewMaximum.mock.calls.map(call=>call.slice(0,2))).toEqual(Array(4).fill(original));
  expect(JSON.stringify(draw(lifecycle))).toContain(original[1]);
  expect(JSON.stringify(draw(lifecycle))).toContain('Fee review confirmed. No bid was sent.');
  expect(api.sendMaximum).not.toHaveBeenCalled();
});

it.each(['live','ended','replaced'] as const)('resolves an authoritatively missing quote while %s',async lifecycle=>{
  draw();await effects();
  const input=nodes(draw()).find(node=>node.type===Input)!;
  (input.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const original=api.reviewMaximum.mock.calls[0].slice(0,2);
  api.reviewMaximum.mockRejectedValueOnce(new ApiError(404,'quote_not_found',''));
  await recoverBid(draw(lifecycle),'Recover fee review');

  const resolved=draw(lifecycle);
  expect(JSON.stringify(resolved)).toContain('The original fee preview is unavailable');
  expect(JSON.stringify(resolved)).not.toContain(original[1]);
  expect(api.reviewMaximum.mock.calls[1].slice(0,2)).toEqual(original);
  expect(api.sendMaximum).not.toHaveBeenCalled();
  if(lifecycle==='live') {
    await submit();
    expect(getQuote).toHaveBeenCalledTimes(2);
  } else if(lifecycle==='replaced') {
    expect(nodes(resolved).some(node=>node.props.children==='Continue to the current auction')).toBe(true);
  }
});

it('shows a live review rejection after relisting before releasing the original auction',async()=>{
  draw();await effects();
  const input=nodes(draw()).find(node=>node.type===Input)!;
  (input.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  let expire!:()=>void;
  api.reviewMaximum.mockImplementationOnce(()=>new Promise((_,reject)=>{
    expire=()=>reject(new ApiError(409,'quote_expired',''));
  }));
  await submit();
  expect(retainAuction).toHaveBeenLastCalledWith(true);
  draw('replaced');await effects();
  expire();
  await Promise.resolve();await Promise.resolve();
  const original=draw('replaced');
  expect(JSON.stringify(original)).toContain('The preview expired');
  expect(retainAuction).toHaveBeenLastCalledWith(true);
  expect(api.sendMaximum).not.toHaveBeenCalled();
  await recoverBid(original,'Continue to the current auction');
  expect(retainAuction).toHaveBeenLastCalledWith(false);
});

it.each(['accepted','stale'] as const)('rechecks access and recovers a %s request after reopening the tab',async outcome=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const original=api.sendMaximum.mock.calls[0][1];

  const storageKey=localStorage.key(0)!;
  const stored=localStorage.getItem(storageKey)!;
  const {amount_minor,owner,...reference}=original;
  expect(JSON.parse(stored)).toEqual({auctionId:'auction-a',intent:reference});
  expect(stored).not.toContain(owner);
  expect(stored).not.toContain(String(amount_minor));
  // Start a fresh tab with only the browser's saved reference.
  settlePendingMaximum('auction-a',original,'bid');
  localStorage.setItem(storageKey,stored);
  hooks.slots=[];hooks.effects=[];
  api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  expect(JSON.stringify(draw('ended'))).not.toContain(original.key);
  await effects();
  expect(JSON.stringify(draw('ended'))).not.toContain(original.key);
  expect(api.lookupMaximum).not.toHaveBeenCalled();

  api.readOwnMaximum.mockResolvedValue({revision:4,amount_minor:null,active:false,watch_id:'watch-a'});
  await vi.advanceTimersByTimeAsync(5000);
  expect(JSON.stringify(draw('ended'))).toContain(original.key);
  await effects();
  if(outcome==='stale') {
    api.lookupMaximum.mockRejectedValueOnce(new ApiError(404,'operation_not_found',''));
  } else api.lookupMaximum.mockResolvedValueOnce({state:outcome});
  await recoverBid(draw('ended'),'Check request status');
  expect(api.lookupMaximum.mock.calls[0].slice(0,2)).toEqual(['auction-a',{...reference,owner}]);
  if(outcome==='stale') {
    api.restoreMaximumIntent.mockResolvedValueOnce(original);
    api.sendMaximum.mockResolvedValueOnce({state:outcome});
    await recoverBid(draw('ended'),'Retry original bid');
    expect(api.restoreMaximumIntent.mock.calls[0].slice(0,2)).toEqual(['auction-a',{...reference,owner}]);
    expect(api.sendMaximum.mock.calls[1].slice(0,2)).toEqual(['auction-a',original]);
  } else expect(api.restoreMaximumIntent).not.toHaveBeenCalled();
  expect(localStorage.getItem(storageKey)).toBeNull();
  expect(JSON.stringify(draw('ended'))).toContain(outcome==='stale'?'The auction changed':'Maximum accepted');
  hooks.slots=[];hooks.effects=[];
  draw('ended');await effects();
  expect(JSON.stringify(draw('ended'))).not.toContain(original.key);
});

it('restores the original fee review after a lost acknowledgement and reload',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.reviewMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const [originalQuote,reviewKey]=api.reviewMaximum.mock.calls[0];
  const storageKey=localStorage.key(0)!;
  const stored=localStorage.getItem(storageKey)!;
  const {intent}=JSON.parse(stored);
  expect(JSON.parse(stored).reviewKey).toBe(reviewKey);
  expect(stored).not.toContain(String(originalQuote.amount_minor));
  expect(stored).not.toContain('access-a');
  settlePendingMaximum('auction-a',{...intent,owner:identity.fingerprint},'review');
  localStorage.setItem(storageKey,stored);

  hooks.slots=[];hooks.effects=[];
  api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  draw('ended');await effects();
  expect(JSON.stringify(draw('ended'))).not.toContain(reviewKey);
  expect(api.restoreMaximumReview).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(5000);
  draw('ended');await effects();
  expect(JSON.stringify(draw('ended'))).toContain(reviewKey);
  api.restoreMaximumReview.mockResolvedValueOnce(originalQuote);
  await recoverBid(draw('ended'),'Recover fee review');
  expect(api.restoreMaximumReview.mock.calls[0].slice(0,2)).toEqual(['auction-a',{...intent,owner:identity.fingerprint}]);
  expect(api.reviewMaximum.mock.calls[1].slice(0,2)).toEqual([originalQuote,reviewKey]);
  expect(api.sendMaximum).not.toHaveBeenCalled();
  expect(localStorage.getItem(storageKey)).toBeNull();
});

it('keeps new admission disabled when the pending reference cannot be read',async()=>{
  vi.spyOn(localStorage,'getItem').mockImplementation(()=>{throw new Error('test-storage-unavailable');});
  draw();await effects();
  await submit();
  expect(JSON.stringify(draw())).toContain('Resolve the pending request');
  expect(getQuote).not.toHaveBeenCalled();
  expect(api.sendMaximum).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

it('keeps the bid unsent if the browser cannot save the reference',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  vi.spyOn(localStorage,'setItem').mockImplementationOnce(()=>{throw new Error('test-storage-full');});
  await submit();
  expect(api.reviewMaximum).not.toHaveBeenCalled();
  expect(api.sendMaximum).not.toHaveBeenCalled();
});

it('checks current auction access after the same buyer receives a new access fingerprint',async()=>{
  draw();await effects();
  (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
  await submit();
  api.sendMaximum.mockRejectedValueOnce(new Error('test-response-lost'));
  await submit();
  const original=api.sendMaximum.mock.calls[0][1];

  hooks.slots=[];hooks.effects=[];
  identity.fingerprint='access-b';
  api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
  draw();await effects();
  expect(JSON.stringify(draw())).not.toContain(original.key);
  expect(api.lookupMaximum).not.toHaveBeenCalled();

  await vi.advanceTimersByTimeAsync(5000);
  expect(JSON.stringify(draw())).toContain(original.key);
  api.lookupMaximum.mockResolvedValueOnce({state:'accepted'});
  await recoverBid(draw(),'Check request status');
  expect(api.lookupMaximum.mock.calls[0].slice(0,2)).toEqual(['auction-a',{...original,owner:'access-b'}]);
});

it.each(['lost response','in flight'] as const)(
  'restores an original fee review after access rotates with the request %s',async scenario=>{
    draw();await effects();
    (nodes(draw()).find(node=>node.type===Input)!.props.onValueChange as (value:string)=>void)('4500');
    await submit();
    api.reviewMaximum.mockImplementationOnce(async()=>{
      if(scenario==='in flight') await new Promise(()=>{});
      throw new Error('test-response-lost');
    });
    await submit();
    const [originalQuote,reference]=api.reviewMaximum.mock.calls[0];
    expect(readPendingMaximum('auction-a','access-other','buyer-other')).toBeNull();

    // A changed access key remounts the form before the private read resolves.
    hooks.slots=[];hooks.effects=[];
    identity.fingerprint='access-b';
    api.readOwnMaximum.mockRejectedValueOnce(new ApiError(403,'denied',''));
    expect(JSON.stringify(draw('ended'))).not.toContain(reference);
    await effects();
    expect(JSON.stringify(draw('ended'))).not.toContain(reference);
    await vi.advanceTimersByTimeAsync(5000);
    expect(JSON.stringify(draw('ended','ar'))).toContain(reference);

    await recoverBid(draw('ended'),'Recover fee review');
    expect(api.reviewMaximum.mock.lastCall?.slice(0,2)).toEqual([
      {...originalQuote,access_fingerprint:'access-b'},reference,
    ]);
    expect(JSON.stringify(draw('ended'))).toContain('Fee review confirmed. No bid was sent.');
    expect(getQuote).toHaveBeenCalledTimes(1);
    expect(api.sendMaximum).not.toHaveBeenCalled();
    expect(api.lookupMaximum).not.toHaveBeenCalled();
    expect(readPendingMaximum('auction-a','access-b','buyer-a')).toBeNull();
  },
);

it('recovers both bids after tabs claim different references before either writes',async()=>{
  const pending=await import('./pending-maximum');
  const first:Parameters<typeof pending.retainPendingReview>[2]={
    key:'test-first-bid',actor_id:'buyer-a',owner:'access-a',watch_id:'watch-a',
    fee_quote_id:'test-first-quote',revision:3,quote_revision:1,policy_revision:'test-policy',amount_minor:450000,
  };
  const second={...first,key:'test-second-bid',fee_quote_id:'test-second-quote'};
  const scope='auction-a';
  const write=localStorage.setItem;
  vi.spyOn(localStorage,'setItem').mockImplementationOnce((key,value)=>{
    expect(pending.retainPendingReview(scope,'auction-a',second,{key:'test-second-review'})).toBe(true);
    expect(pending.retainPendingMaximum(scope,'auction-a',second)).toBe(true);
    write(key,value);
  });
  expect(pending.retainPendingReview(scope,'auction-a',first,{key:'test-first-review'})).toBe(true);
  expect(pending.retainPendingMaximum(scope,'auction-a',first)).toBe(true);
  expect(localStorage.length).toBe(2);

  draw('ended');await effects();
  expect(JSON.stringify(draw('ended'))).toContain(second.key);
  api.lookupMaximum.mockResolvedValueOnce({state:'accepted'});
  await recoverBid(draw('ended'),'Check request status');
  expect(api.lookupMaximum.mock.calls[0][1].key).toBe(second.key);
  await recoverBid(draw('ended'),'Continue to the current auction');
  draw('ended');await effects();
  expect(JSON.stringify(draw('ended'))).toContain(first.key);
  api.lookupMaximum.mockResolvedValueOnce({state:'stale'});
  await recoverBid(draw('ended'),'Check request status');
  expect(api.lookupMaximum.mock.calls[1][1].key).toBe(first.key);
  expect(localStorage.length).toBe(0);
});
