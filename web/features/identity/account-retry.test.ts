import { beforeEach, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
const harness = vi.hoisted(()=>({slots:[] as unknown[],cursor:0,invoke:vi.fn(),revoke:vi.fn(),locale:'en' as 'en'|'ar',session:null as null|{account:{id:string};access_fingerprint:string},refresh:vi.fn(),state:'signed-out'}));
vi.mock('react',async()=>({...(await vi.importActual('react')),useEffect:()=>{},useSyncExternalStore:(_subscribe:unknown,_snapshot:unknown,server:()=>unknown)=>server(),
  useState:(initial:unknown)=>{const index=harness.cursor++;if(!(index in harness.slots)) harness.slots[index]=initial;return [harness.slots[index],(value:unknown)=>{harness.slots[index]=value;}];},
  useRef:(initial:unknown)=>{const index=harness.cursor++;if(!(index in harness.slots))harness.slots[index]={current:initial};return harness.slots[index];}}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()})}));
vi.mock('@/lib/api/client',()=>({request:harness.invoke,ApiError:class extends Error{constructor(public status:number,public code='',_message=''){super(_message || 'request failed');}}}));
vi.mock('./session',()=>({useSession:()=>harness.session,useSessionState:()=>harness.state,accountApi:'/accounts',beginSession:vi.fn(),signOut:harness.revoke,safeReturnPath:()=>'/account',refreshSession:harness.refresh}));
vi.mock('./shared',()=>({useIdentityCopy:()=>({locale:harness.locale,t:new Proxy({},{get:(_target,key)=>String(key)})}),ErrorNotice:()=>null}));
import AccountView from './account-view';
import { ApiError } from '@/lib/api/client';
type Node = ReactElement<Record<string, unknown>>;
function nodes(value:unknown):Node[] {
  if(Array.isArray(value))return value.flatMap(nodes);
  if(!value || typeof value!=='object' || !('props' in value))return [];
  const node=value as Node;return [node,...nodes(node.props.children)];
}
function render(){harness.cursor=0;const content=AccountView({initialMode:'recovery'});return nodes((content.type as (props:typeof content.props)=>ReactElement)(content.props));}
beforeEach(()=>{harness.slots=[];harness.cursor=0;harness.invoke.mockReset();harness.locale='en';harness.session=null;harness.state='signed-out';
  vi.stubGlobal('FormData',class { *[Symbol.iterator](){yield ['email','sample@example.test'];} });});
it('retains the exact recovery request across mode and language changes after a lost response',async()=>{
  harness.invoke.mockRejectedValueOnce(new Error('response lost')).mockRejectedValueOnce(new ApiError(429,'try_later','')).mockResolvedValueOnce({accepted:true});
  let tree=render();
  const submit=tree.find(node=>node.type==='form')!.props.onSubmit as (event:unknown)=>Promise<void>;
  await submit({preventDefault(){},currentTarget:{reset:vi.fn()}});
  const original=harness.invoke.mock.calls[0];
  tree=render();
  const switchMode=tree.find(node=>'onValueChange' in node.props)!.props.onValueChange as (value:string)=>void;
  switchMode('signin');tree=render();harness.locale='ar';tree=render();
  switchMode('recovery');tree=render();
  const retry=tree.find(node=>node.props.children==='retry')!;
  await (retry.props.onClick as ()=>Promise<void>)();
  tree=render();
  await (tree.find(node=>node.props.children==='retry')!.props.onClick as ()=>Promise<void>)();
  expect(harness.invoke).toHaveBeenCalledTimes(3);
  expect(harness.invoke.mock.calls[2]).toEqual(original);
  expect(harness.invoke.mock.calls[1]).toEqual(original);
  expect(JSON.parse(original[1].body).locale).toBe('en');
  expect(render().some(node=>node.props.children==='retry')).toBe(false);
});

it('replaces private form identity on every access change but preserves it across languages',()=>{
  const key=()=>{harness.cursor=0;return AccountView({}).key;};
  const signedOut=key();
  harness.session={account:{id:'test-person'},access_fingerprint:'test-access-one'};harness.state='signed-in';
  const signedIn=key();expect(signedIn).not.toBe(signedOut);
  harness.locale='ar';expect(key()).toBe(signedIn);
  harness.session.access_fingerprint='test-access-two';expect(key()).not.toBe(signedIn);
  const refreshed=key();harness.state='unavailable';expect(key()).not.toBe(refreshed);
  harness.session=null;harness.state='signed-out';expect(key()).toBe(signedOut);
});

it('keeps failed remote revocation and retry outside the replaced private form',async()=>{
  harness.session={account:{id:'test-person'},access_fingerprint:'test-access'};
  harness.revoke.mockImplementationOnce(async()=>{harness.session=null;throw new Error('response lost');}).mockResolvedValueOnce(undefined);
  harness.cursor=0;const before=AccountView({});
  await before.props.revoke();
  harness.cursor=0;const after=AccountView({});
  expect(after.key).not.toBe(before.key);expect(after.props.revokeFailed).toBe(true);
  await after.props.revoke();harness.cursor=0;expect(AccountView({}).props.revokeFailed).toBe(false);
});

it('refreshes first-attempt password access and recovers a lost response after gateway denial',async()=>{
  harness.session={account:{id:'test-person'},access_fingerprint:'test-access'};
  harness.refresh.mockResolvedValue({access_token:'test-fresh-token'});
  vi.stubGlobal('FormData',class {get(name:string){return name==='new_password'?'test-new-password-1234':'test-old-password-1234';}});
  vi.stubGlobal('window',{history:{replaceState:vi.fn()},location:{pathname:'/en/account'}});
  harness.invoke.mockRejectedValueOnce(new Error('response lost')).mockRejectedValueOnce(new ApiError(401,'unauthorized','')).mockResolvedValueOnce({sign_in_required:true});
  let tree=render();
  const form=tree.find(node=>node.type==='form')!;
  await (form.props.onSubmit as (event:unknown)=>Promise<void>)({preventDefault(){},currentTarget:{reset:vi.fn()}});
  expect(harness.refresh).toHaveBeenCalled();
  const original=harness.invoke.mock.calls[0];
  expect(original[1].headers.Authorization).toBe('Bearer test-fresh-token');
  tree=render();await (tree.find(node=>node.props.children==='retry')!.props.onClick as ()=>Promise<void>)();
  await vi.waitFor(()=>expect(harness.slots[8]).toBe(false));
  expect(harness.invoke.mock.calls[1]).toEqual(original);
  const receipt=harness.invoke.mock.calls[2];
  expect(receipt[0]).toBe('/accounts/reset');
  expect(receipt[1].headers['Idempotency-Key']).toBe(original[1].headers['Idempotency-Key']);
  expect(receipt[1].headers.Authorization).toBeUndefined();
  expect(JSON.parse(receipt[1].body).authorization).toBe('Bearer test-fresh-token');
  expect(render().some(node=>node.props.children==='retry')).toBe(false);
});

it('allows correction after a definitive first-attempt current-password rejection',async()=>{
  harness.session={account:{id:'test-person'},access_fingerprint:'test-access'};
  harness.refresh.mockResolvedValue({access_token:'test-fresh-token'});
  vi.stubGlobal('FormData',class {get(name:string){return name==='new_password'?'test-new-password-1234':'test-wrong-password-1234';}});
  harness.invoke.mockRejectedValueOnce(new ApiError(401,'invalid_credentials',''));
  const form=render().find(node=>node.type==='form')!;
  await (form.props.onSubmit as (event:unknown)=>Promise<void>)({preventDefault(){},currentTarget:{reset:vi.fn()}});
  expect(render().some(node=>node.props.children==='retry')).toBe(false);
  expect((harness.slots[6] as {current:unknown}).current).toBe(null);
});


it('allows corrected password submission after a lost response followed by definitive rejection',async()=>{
  harness.session={account:{id:'test-person'},access_fingerprint:'test-access'};
  harness.refresh.mockResolvedValue({access_token:'test-fresh-token'});
  let currentPassword='test-wrong-password-1234';
  vi.stubGlobal('FormData',class {get(name:string){return name==='new_password'?'test-new-password-1234':currentPassword;}});
  harness.invoke.mockRejectedValueOnce(new Error('response lost'))
    .mockRejectedValueOnce(new ApiError(401,'invalid_credentials',''))
    .mockRejectedValueOnce(new ApiError(401,'invalid_credentials',''));
  const submit=async()=>{
    const form=render().find(node=>node.type==='form')!;
    await (form.props.onSubmit as (event:unknown)=>Promise<void>)({preventDefault(){},currentTarget:{reset:vi.fn()}});
  };
  await submit();
  const original=harness.invoke.mock.calls[0];
  await (render().find(node=>node.props.children==='retry')!.props.onClick as ()=>Promise<void>)();
  expect(harness.invoke).toHaveBeenCalledTimes(2);
  expect(harness.invoke.mock.calls[1]).toEqual(original);
  expect(render().some(node=>node.props.children==='retry')).toBe(false);
  expect((harness.slots[6] as {current:unknown}).current).toBe(null);
  currentPassword='test-correct-password-1234';
  await submit();
  const corrected=harness.invoke.mock.calls[2];
  expect(corrected[0]).toBe('/accounts/password');
  expect(JSON.parse(corrected[1].body).current_password).toBe(currentPassword);
  expect(corrected[1].headers['Idempotency-Key']).not.toBe(original[1].headers['Idempotency-Key']);
});
