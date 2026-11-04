import { beforeEach, describe, expect, it, vi } from 'vitest';
const { invoke, access } = vi.hoisted(() => ({ invoke: vi.fn(), access: vi.fn() }));
vi.mock('@/lib/api/client', () => ({
  request: invoke,
  ApiError: class ApiError extends Error { constructor(public status:number,public code:string,public requestId:string) { super(code); } }
}));
vi.mock('@/shell/private-state', () => ({ setAccessContext: access }));
const sample = { access_token:'memory-only',token_type:'Bearer' as const,expires_in:300,account:{id:'subject',email:'demo@example.test',display_name:'Demo'},principal:{actor:{subject_id:'subject',session_id:'lineage',organization_id:null},roles:['buyer'],permissions:[],organizations:[],organization_grants:[]},access_fingerprint:'one-way-fingerprint' };
function deferred<T>() { let resolve!:(value:T)=>void; const promise=new Promise<T>(accept=>{resolve=accept;});return {promise,resolve}; }
beforeEach(() => { vi.resetModules();invoke.mockReset();access.mockReset();vi.stubGlobal('BroadcastChannel',undefined);vi.stubGlobal('navigator',{ locks:{ request:(_name:string,callback:()=>unknown)=>Promise.resolve(callback()) } }); });

describe('safe intended destination',()=>{
  it('preserves owned localized route/query and rejects external or ambiguous paths',async()=>{
    const {safeReturnPath,signInHref}=await import('./session');
    for(const bad of ['https://evil.test','//evil.test','/\\evil.test','/admin','/watches/../../operations/dashboard','/watches/%2e%2e/%2e%2e/operations','/watches/%5cevil','/account#secret','/api/web/v1/identity','javascript:alert(1)'])expect(safeReturnPath(bad)).toBe('/account');
    expect(safeReturnPath('/ar/watches/sample?mode=auction')).toBe('/watches/sample?mode=auction');
    expect(signInHref('/buyer','ar')).toBe('/ar/account?next=%2Fbuyer');
    expect(signInHref('/operations/verification','ar')).toBe('/ar/account?next=%2Foperations%2Fverification');
    expect(safeReturnPath('/watches/%2e%2e/operations/dashboard')).toBe('/account');
  });
});
it('coalesces refresh and retains credentials only in module memory',async()=>{
  const api=await import('./session');const pending=deferred<typeof sample>();invoke.mockReturnValue(pending.promise);
  const one=api.refreshSession(),two=api.refreshSession();expect(invoke).toHaveBeenCalledTimes(1);
  pending.resolve(sample);expect(await one).toEqual(sample);expect(await two).toEqual(sample);
  expect(access).toHaveBeenLastCalledWith('one-way-fingerprint',['buyer']);
});
it('fences late refresh publication after logout and revokes after cookie rotation',async()=>{
  const api=await import('./session');const pending=deferred<typeof sample>();
  invoke.mockImplementation((path:string)=>path.endsWith('/refresh')?pending.promise:Promise.resolve({signed_out:true}));
  const refresh=api.refreshSession();const logout=api.signOut();pending.resolve(sample);
  await refresh;await logout;
  expect(access).toHaveBeenLastCalledWith(null,undefined);
  expect(access.mock.calls.some(call=>call[0]===sample.access_fingerprint)).toBe(false);
  expect(invoke.mock.calls.map(call=>call[0])).toEqual(['/api/web/v1/identity/v1/accounts/refresh','/api/web/v1/identity/v1/accounts/logout']);
});
it('serializes login after a pending refresh and publishes only the new account',async()=>{
  const api=await import('./session');const pending=deferred<typeof sample>();
  const newer={...sample,access_fingerprint:'new-account'};
  invoke.mockImplementation((path:string)=>path.endsWith('/refresh')?pending.promise:Promise.resolve(newer));
  const refresh=api.refreshSession();
  const login=api.beginSession('login','{}','login-operation');
  expect(invoke).toHaveBeenCalledTimes(1);pending.resolve(sample);
  await refresh;expect(await login).toEqual(newer);
  expect(access.mock.calls.some(call=>call[0]===sample.access_fingerprint)).toBe(false);
  expect(access).toHaveBeenLastCalledWith('new-account',['buyer']);
});
it('fences a pending login before server logout',async()=>{
  const api=await import('./session');const pending=deferred<typeof sample>();
  invoke.mockImplementation((path:string)=>path.endsWith('/login')?pending.promise:Promise.resolve({signed_out:true}));
  const login=api.beginSession('login','{}','login-operation');
  await Promise.resolve();await Promise.resolve();
  const logout=api.signOut();pending.resolve(sample);
  await expect(login).rejects.toMatchObject({code:'session_changed'});await logout;
  expect(access.mock.calls.some(call=>call[0]===sample.access_fingerprint)).toBe(false);
});
it('never sends an old form payload under a newly signed-in account',async()=>{
  const api=await import('./session');api.acceptSession({...sample,access_fingerprint:'new-owner'});
  await expect(api.authenticatedRequest('/api/web/v1/identity/v1/private-seller/applications',{
    method:'POST',accessFingerprint:sample.access_fingerprint,body:'private old-owner evidence'
  })).rejects.toMatchObject({status:401});
  expect(invoke).not.toHaveBeenCalled();
});
it('rejects a late private response after identity changes',async()=>{
  const api=await import('./session');api.acceptSession(sample);
  const pending=deferred<{private:string}>();invoke.mockReturnValue(pending.promise);
  const read=api.authenticatedRequest('/api/web/v1/orders/v1/mine');
  api.acceptSession({...sample,access_fingerprint:'different-account'});
  pending.resolve({private:'prior-account-row'});
  await expect(read).rejects.toMatchObject({status:401});
});
