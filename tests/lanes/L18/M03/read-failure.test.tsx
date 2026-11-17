import { beforeEach, expect, it, vi } from 'vitest';
import { isValidElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const state=vi.hoisted(()=>({values:[] as unknown[],index:0,locale:'en',buttons:[] as {children?:unknown;onClick?:()=>Promise<void>|void}[],read:vi.fn()}));
vi.mock('react',async original=>({...await original<typeof import('react')>(),useMemo:(factory:()=>unknown)=>factory(),useRef:()=>({current:false}),useEffect:()=>{},useState:(initial:unknown)=>{
 const index=state.index++;
 if(!(index in state.values))state.values[index]=initial;
 return [state.values[index],(value:unknown)=>{state.values[index]=value;}];
}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:state.read,useSession:()=>null,signInHref:()=>'/account'}));
vi.mock('@/lib/api/client',async original=>({...await original<typeof import('../../../../web/lib/api/client')>(),request:state.read}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:{items:[],total:0,can_moderate:true,assigned_question_ids:['q']},refetch:vi.fn()})}));
import { ApiError } from '../../../../web/lib/api/client';
import { Questions } from '../../../../web/features/listing-questions/view';
import { copy } from '../../../../web/features/listing-questions/copy';
function render(){state.index=0;state.buttons=[];const tree=Questions({listing:'listing',signedIn:true,onPending:()=>{}});
 function visit(node:unknown){if(Array.isArray(node)){node.forEach(visit);return;}if(isValidElement<{children?:unknown;onClick?:()=>void}>(node)){if(node.props.onClick)state.buttons.push(node.props);visit(node.props.children);}}
 visit(tree);return renderToStaticMarkup(tree);}
async function press(label:string){const button=state.buttons.find(button=>button.children===label);if(!button)throw new Error(JSON.stringify(state.buttons.map(item=>item.children)));button.onClick!();await new Promise(resolve=>setTimeout(resolve,0));}
beforeEach(()=>{state.values=[];state.index=0;state.read.mockReset();});
for(const locale of ['en','ar'] as const)for(const kind of ['suggest','review'] as const){
 for(const failure of ['timeout','503','403','401'] as const)it(`${kind} distinguishes ${failure} in ${locale}`,async()=>{
  state.locale=locale;const c=copy[locale];
  state.read.mockRejectedValueOnce(failure==='timeout'?new Error('timeout'):new ApiError(Number(failure),'read_error',''));
  render();await press(kind==='suggest'?c.check:c.review);
  const html=render();
  if(failure==='401'||failure==='403'){
   expect(html).toContain(c.denied);expect(html).not.toContain(c.readRecovery);
  }else{
   expect(html).toContain(c.unavailable);expect(html).toContain(c.readRecovery);expect(html).not.toContain(c.denied);
   state.read.mockResolvedValueOnce(kind==='suggest'?{items:[]}:{id:'q',question:'Question',reports:[],appeals:[]});
   await press(c.retry);expect(state.read).toHaveBeenCalledTimes(2);
   expect(state.read.mock.calls[1]).toEqual(state.read.mock.calls[0]);
   expect(render()).not.toContain(c.readRecovery);
  }
 });
}

it('keeps all matching answers reachable with the server total',async()=>{
 state.locale='en';
 const rows=Array.from({length:20},(_,i)=>({id:`match-${i}`,question:`Matching question ${i}`,answer:'Yes',seller:'seller',revision:2}));
 state.read.mockResolvedValueOnce({items:rows,total:21,page:0});
 render();await press(copy.en.check);
 expect(render()).toContain('Total questions: 21');
 state.read.mockResolvedValueOnce({items:[{...rows[0],id:'match-20',question:'Last matching answer'}],total:21,page:1});
 const next=state.buttons.filter(button=>button.children===copy.en.next).at(-1);
 await next!.onClick!();
 const html=render();
 expect(html).toContain('Last matching answer');
 expect(JSON.parse(state.read.mock.calls[1][1].body)).toEqual({text:'',page:1});
 expect(state.read.mock.calls.every(call=>call[0].endsWith('/suggest'))).toBe(true);
});

it('pages private reports and appeals independently with server totals',async()=>{
 state.locale='en';
 const first={id:'q',question:'Question',revision:43,reports:[{reason:'Recent report',created_at:''}],appeals:[{reason:'Recent appeal',created_at:''}],reports_total:21,appeals_total:21,reports_page:0,appeals_page:0};
 state.read.mockResolvedValueOnce(first);
 render();await press(copy.en.review);
 render();
 expect(state.values).toContainEqual(first);
 const reportNext=state.buttons.filter(button=>button.children===copy.en.next).at(-2);
 state.read.mockResolvedValueOnce({...first,reports_page:1,reports:[{reason:'Oldest report',created_at:''}]});
 await reportNext!.onClick!();await new Promise(resolve=>setTimeout(resolve,0));
 render();expect(state.values).toContainEqual(expect.objectContaining({reports_page:1,reports:[{reason:'Oldest report',created_at:''}]}));
 expect(state.read.mock.calls[1][0]).toContain('reports_page=1&appeals_page=0');
 const appealNext=state.buttons.filter(button=>button.children===copy.en.next).at(-1);
 state.read.mockResolvedValueOnce({...first,reports_page:1,appeals_page:1,appeals:[{reason:'Oldest appeal',created_at:''}]});
 await appealNext!.onClick!();await new Promise(resolve=>setTimeout(resolve,0));
 render();expect(state.values).toContainEqual(expect.objectContaining({appeals_page:1,appeals:[{reason:'Oldest appeal',created_at:''}]}));
 expect(state.read.mock.calls[2][0]).toContain('reports_page=1&appeals_page=1');
 expect(state.read.mock.calls.every(call=>call[0].includes('/review/'))).toBe(true);
});

for(const failure of [403,503])it(`clears private content when a review page fails with ${failure}`,async()=>{
 state.locale='en';
 const privateRow={id:'q',question:'Restricted question',answer:'Restricted answer',revision:3,reports:[],appeals:[],reports_total:21,appeals_total:0,reports_page:0,appeals_page:0};
 state.read.mockResolvedValueOnce(privateRow);
 render();await press(copy.en.review);render();
 expect(state.values.filter(value=>value===privateRow)).toHaveLength(2);
 state.read.mockRejectedValueOnce(new ApiError(failure,'read_error',''));
 const next=state.buttons.filter(button=>button.children===copy.en.next).at(-2);
 await next!.onClick!();await new Promise(resolve=>setTimeout(resolve,0));
 render();expect(state.values).not.toContainEqual(privateRow);
});

for(const denial of [401,403,409])it(`retains an uncertain command through ${denial} and reconciles before replacement`,async()=>{
 state.locale='en';
 state.read.mockRejectedValueOnce(new Error('Lost response'));
 render();await press(copy.en.send);
 render();
 const command=state.values.find(value=>value!==null&&typeof value==='object'&&'operation_id' in value) as {operation_id:string;question_id:string};
 expect(command).toBeDefined();
 state.read.mockRejectedValueOnce(new ApiError(denial,'access_error',''));
 await press(copy.en.retry);render();
 expect(state.values).toContain(command);
 expect(state.read.mock.calls[1][0]).toContain(`/operations/${command.operation_id}`);
 const receipt={...command,state:'published',revision:1};
 state.read.mockResolvedValueOnce(receipt);
 await press(copy.en.retry);render();
 expect(state.values).not.toContain(command);
 expect(state.values).toContainEqual(receipt);
 expect(state.read.mock.calls).toHaveLength(3);
 expect(state.read.mock.calls[2]).toEqual(state.read.mock.calls[1]);
 expect(state.read.mock.calls.filter(call=>call[0].endsWith('/commands'))).toHaveLength(1);
});

it('replays the exact uncertain command when lookup has no receipt',async()=>{
 state.locale='en';state.read.mockRejectedValueOnce(new Error('Lost response'));
 render();await press(copy.en.send);render();
 state.read.mockResolvedValueOnce({state:'pending'}).mockRejectedValueOnce(new ApiError(403,'denied',''));
 await press(copy.en.retry);render();
 expect(state.read.mock.calls[2]).toEqual(state.read.mock.calls[0]);
 const command=JSON.parse(state.read.mock.calls[0][1].body);
 expect(state.values).toContainEqual(command);
});
