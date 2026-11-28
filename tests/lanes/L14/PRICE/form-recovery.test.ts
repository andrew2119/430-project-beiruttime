import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';

const harness=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,requests:vi.fn(),pending:[] as Promise<unknown>[],locale:'en'}));
vi.mock('react',async original=>({...await original<typeof import('react')>(),
 useState:(initial:unknown)=>{const index=harness.cursor++;if(!(index in harness.slots))harness.slots[index]=initial;return [harness.slots[index],(value:unknown)=>{harness.slots[index]=value;}];},
 useRef:(initial:unknown)=>{const index=harness.cursor++;if(!(index in harness.slots))harness.slots[index]={current:initial};return harness.slots[index];},
}));
vi.mock('@tanstack/react-query',()=>({
 useQuery:()=>({isSuccess:false}),useQueryClient:()=>({setQueryData:vi.fn(),invalidateQueries:vi.fn()}),
 useMutation:({mutationFn,onSuccess}:{mutationFn:(body:unknown)=>Promise<unknown>;onSuccess?:(result:unknown,body:unknown)=>void})=>({mutate:(body:unknown)=>{harness.pending.push(mutationFn(body).then(result=>onSuccess?.(result,body)).catch(()=>undefined));},reset:()=>{}}),
}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'current'}),authenticatedRequest:harness.requests}));
vi.mock('../../../../web/features/pricing/shared',()=>({
 useCopy:()=>({locale:harness.locale,t:{}}),Desk:'desk',PrivateGate:'gate',Failure:'failure',
 command:(body:unknown,key:string,method='POST')=>({method,headers:{'Idempotency-Key':key},body:JSON.stringify(body)}),
}));
vi.mock('@beirut-time/ui',()=>Object.fromEntries(['AnimatedList','BidiReference','Button','Card','Input','Select','CardHead','LoadingRows','Notice','SectionState'].map(name=>[name,name])));
import PricingPage from '../../../../web/features/pricing/quotes';
import BuyingPage from '../../../../web/features/pricing/buying';

type Node=ReactElement<Record<string,unknown>>;
function nodes(value:unknown):Node[]{
 if(Array.isArray(value))return value.flatMap(nodes);
 if(!value||typeof value!=='object'||!('props' in value))return [];
 const node=value as Node;
 return [node,...nodes(node.props.children)];
}
function mount(page:(props:Record<string,never>)=>unknown){
 const root=page({});
 const inner=nodes(root).find(node=>typeof node.type==='function')!;
 return ()=>{harness.cursor=0;return (inner.type as (props:unknown)=>unknown)(inner.props);};
}
function change(tree:unknown,name:string,value:string){
 const field=nodes(tree).find(node=>node.props.name===name)!;
 (field.props.onChange as (event:unknown)=>void)({target:{value}});
}
async function submit(tree:unknown,name:string){
 const form=nodes(tree).find(node=>node.type==='form'&&nodes(node.props.children).some(field=>field.props.name===name))!;
 (form.props.onSubmit as (event:unknown)=>void)({preventDefault:()=>{}});
 await Promise.all(harness.pending.splice(0));
}
beforeEach(()=>{harness.slots=[];harness.cursor=0;harness.locale='en';harness.pending=[];harness.requests.mockReset();harness.requests.mockRejectedValue(new Error('Response unavailable'));});
afterEach(()=>{vi.useRealTimers();});
describe('Form command recovery',()=>{
 it('renews unchanged terms after confirmed success and preview expiry',async()=>{
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-17T12:00:00Z'));
  const render=mount(PricingPage);
  change(render(),'subject','00000000-0000-0000-0000-000000000001');
  harness.requests.mockResolvedValueOnce({id:'quote-1',expires_at:'2026-11-17T12:15:00Z'});
  await submit(render(),'subject');
  vi.setSystemTime(new Date('2026-11-17T12:15:00Z'));
  change(render(),'price','6000.00');
  change(render(),'price','5000.00');
  harness.locale='ar';
  await submit(render(),'subject');
  await submit(render(),'subject');
  const calls=harness.requests.mock.calls.map(([url,options])=>({url,...options}));
  expect(calls).toHaveLength(3);
  expect(calls[1].body).toBe(calls[0].body);
  expect(calls[1].headers['Idempotency-Key']).not.toBe(calls[0].headers['Idempotency-Key']);
  expect(calls[2]).toEqual(calls[1]);
 });
 it.each([
  {page:PricingPage,subject:'subject',amount:'price'},
  {page:BuyingPage,subject:'draft_subject',amount:'draft_amount'},
 ])('reuses the original reference after changed input and language for $subject',async({page,subject,amount})=>{
  const render=mount(page);
  change(render(),subject,'00000000-0000-0000-0000-000000000001');
  change(render(),amount,'5000.00');
  await submit(render(),subject);
  change(render(),amount,'6000.00');
  await submit(render(),subject);
  harness.locale='ar';
  change(render(),amount,'5000.00');
  await submit(render(),subject);
  expect(harness.requests).toHaveBeenCalledTimes(3);
  const calls=harness.requests.mock.calls.map(([url,options])=>({url,...options}));
  expect(calls[0].headers['Idempotency-Key']).toBeTruthy();
  expect(calls[1].headers['Idempotency-Key']).not.toBe(calls[0].headers['Idempotency-Key']);
  expect(calls[2]).toEqual(calls[0]);
 });
});
