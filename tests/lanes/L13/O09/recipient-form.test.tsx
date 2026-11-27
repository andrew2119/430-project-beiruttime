import {beforeEach,expect,it,vi} from 'vitest';
import {QueryClient} from '@tanstack/react-query';
import type {ReactElement} from 'react';

const hooks=vi.hoisted(()=>({values:[] as unknown[],cursor:0,locale:'en',sessionState:'authenticated',owner:'owner' as string|undefined,refresh:vi.fn(),request:vi.fn()}));
const cache=new QueryClient();
vi.mock('@tanstack/react-query',async original=>({...await original<typeof import('@tanstack/react-query')>(),useQueryClient:()=>cache}));
vi.mock('react',async original=>({...await original<typeof import('react')>(),
 useState:(initial:unknown)=>{const index=hooks.cursor++;if(!(index in hooks.values))hooks.values[index]=initial;return [hooks.values[index],(value:unknown)=>{hooks.values[index]=value;}];},
 useRef:(initial:unknown)=>{const index=hooks.cursor++;if(!(index in hooks.values))hooks.values[index]={current:initial};return hooks.values[index];},
 useEffect:()=>{},
}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>hooks.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>hooks.owner?{access_fingerprint:hooks.owner,principal:{actor:{subject_id:'subject',organization_id:null}}}:null,useSessionState:()=>hooks.sessionState,refreshSession:hooks.refresh,signInHref:(_next:string,locale:string)=>`/${locale}/account`,authenticatedRequest:hooks.request}));
vi.mock('@beirut-time/ui',()=>({Button:'button',Card:'section',Input:'input',Label:'label',Radio:'radio',SectionState:'output'}));
vi.mock('@/shell/page-header',()=>({PageHeader:'header',PageLayout:'article'}));
import RecipientPage from '../../../../web/features/payout-recipients/page';
type Node=ReactElement<{children?:Node|Node[];[key:string]:unknown}>;
function render(){
 hooks.cursor=0;
 const page=RecipientPage();
 return (page.type as (props:typeof page.props)=>Node)(page.props);
}
function nodes(node:Node):Node[]{
 if(!node||typeof node!=='object')return [];
 return [node,...[node.props?.children].flat(Infinity).flatMap(child=>nodes(child as Node))];
}
function find(tree:Node,type:string,id?:string){return nodes(tree).find(node=>(id?node.props.id===id:type==='button'?typeof node.props.onClick==='function':node.type===type))!;}
function enter(tree:Node,id:string,value:string){(find(tree,'input',id).props.onChange as (event:unknown)=>void)({target:{value}});}
async function load(){const tree=render();await (find(tree,'button').props.onClick as ()=>Promise<void>)();await new Promise(resolve=>setTimeout(resolve,0));}
async function submit(){const tree=render();(find(tree,'form').props.onSubmit as (event:unknown)=>void)({preventDefault(){}});await new Promise(resolve=>setTimeout(resolve,0));await new Promise(resolve=>setTimeout(resolve,0));}
const scope={schema_version:1,subject_id:'subject',organization_id:null,revision:0};
beforeEach(()=>{cache.clear();hooks.values=[];hooks.cursor=0;hooks.locale='en';hooks.owner='owner';hooks.sessionState='authenticated';hooks.refresh.mockReset();hooks.refresh.mockResolvedValue(null);hooks.request.mockReset();hooks.request.mockResolvedValue({...scope,state:'succeeded'});});
it('retains private inputs, method and exact pending operation across in-place language changes',async()=>{
 await load();let tree=render();
 enter(tree,'recipient-reference','synthetic_Ab_1');enter(tree,'recipient-proof','private-verification');
 const radio=nodes(tree).find(node=>node.props.value==='omt')!;
 expect(typeof radio.type).toBe('function');
 (radio.props.onChange as ()=>void)();
 hooks.locale='ar';tree=render();
 expect(find(tree,'input','recipient-reference').props.value).toBe('synthetic_Ab_1');
 expect(find(tree,'input','recipient-proof').props.value).toBe('private-verification');
 expect(nodes(tree).find(node=>node.props.value==='omt')?.props.checked).toBe(true);
 expect(hooks.request).toHaveBeenCalledTimes(1);
 hooks.request.mockRejectedValueOnce(new Error());await submit();
 const body=hooks.request.mock.calls[1][1].body;
 const operation=JSON.parse(body).operation_id;
 hooks.locale='en';tree=render();
 expect(find(tree,'input','recipient-proof').props.value).toBe('private-verification');
 expect(find(tree,'fieldset').props.disabled).toBe(true);
 hooks.locale='ar';tree=render();
 expect(find(tree,'input','recipient-reference').props.value).toBe('synthetic_Ab_1');
 expect(find(tree,'input','recipient-proof').props.value).toBe('private-verification');
 expect(nodes(tree).find(node=>node.props.value==='omt')?.props.checked).toBe(true);
 expect(hooks.request).toHaveBeenCalledTimes(2);
 hooks.request.mockResolvedValueOnce({...scope,state:'pending',operation_id:operation,pending_reason:'authority_unavailable'});
 await submit();
 expect(hooks.request.mock.calls[2][0]).toContain('/operations/'+operation);
 expect(hooks.request.mock.calls[2][1].method).toBe('GET');
 expect(hooks.request.mock.calls[1][1].body).toBe(body);
});
it('allows correction after a definitive validation denial without an operation ID',async()=>{
 await load();let tree=render();enter(tree,'recipient-reference','synthetic_one');enter(tree,'recipient-proof','invalid');
 hooks.request.mockResolvedValueOnce({...scope,state:'denied',operation_id:null,code:'invalid_request'});
 await submit();tree=render();
 expect(find(tree,'fieldset').props.disabled).toBe(false);
 expect(find(tree,'input','recipient-proof').props.value).toBe('');
 expect(find(tree,'input','recipient-reference').props.value).toBe('synthetic_one');
 expect(find(tree,'button').props.disabled).toBe(false);
 enter(tree,'recipient-proof','corrected');await submit();
 expect(hooks.request.mock.calls[2][1].method).toBe('POST');
 expect(JSON.parse(hooks.request.mock.calls[2][1].body).operation_id).not.toBe(JSON.parse(hooks.request.mock.calls[1][1].body).operation_id);
});
it('clears private fields and disables submission after a denied refresh',async()=>{
 await load();let tree=render();enter(tree,'recipient-reference','synthetic_one');enter(tree,'recipient-proof','private-verification');
 hooks.request.mockResolvedValueOnce({...scope,state:'denied',code:'access_denied'});
 await load();tree=render();
 expect(find(tree,'input','recipient-reference').props.value).toBe('');
 expect(find(tree,'input','recipient-proof').props.value).toBe('');
 expect(find(tree,'fieldset').props.disabled).toBe(true);
 await submit();expect(hooks.request).toHaveBeenCalledTimes(2);
});

it('clears private selection after submission access denial',async()=>{
 await load();let tree=render();enter(tree,'recipient-reference','synthetic_one');enter(tree,'recipient-proof','private-verification');
 (nodes(tree).find(node=>node.props.value==='omt')!.props.onChange as ()=>void)();
 hooks.request.mockImplementationOnce(async (_path,options)=>({...scope,state:'denied',code:'access_denied',operation_id:JSON.parse(options.body).operation_id}));
 await submit();tree=render();
 expect(find(tree,'input','recipient-reference').props.value).toBe('');
 expect(find(tree,'input','recipient-proof').props.value).toBe('');
 expect(nodes(tree).find(node=>node.props.value==='bank')?.props.checked).toBe(true);
 expect(find(tree,'fieldset').props.disabled).toBe(true);
 await submit();expect(hooks.request).toHaveBeenCalledTimes(2);
});
it.each(['en','ar'])('offers sign-in and restoration recovery in %s',async locale=>{
 hooks.locale=locale;hooks.owner=undefined;hooks.sessionState='signed-out';
 let tree=render();expect(find(tree,'a').props.href).toBe(`/${locale}/account`);
 hooks.sessionState='unavailable';tree=render();
 expect(nodes(tree).find(node=>node.props.body)?.props.title).toBe(locale==='en'?'Session unavailable':'الجلسة غير متاحة');
 await (find(tree,'button').props.onClick as ()=>void)();
 expect(hooks.refresh).toHaveBeenCalledTimes(1);expect(hooks.request).not.toHaveBeenCalled();
 hooks.sessionState='restoring';tree=render();expect(nodes(tree).some(node=>typeof node.props.onClick==='function')).toBe(false);
});

it('renders retained current content on the first frame of a return visit',async()=>{
 await load();
 hooks.values=[];
 const tree=render();
 expect(nodes(tree).some(node=>node.props.title==='No recipient saved')).toBe(true);
 expect(find(tree,'fieldset').props.disabled).toBe(false);
 expect(hooks.request).toHaveBeenCalledTimes(1);
});
