import { afterEach, expect, it, vi } from 'vitest';
afterEach(()=>{vi.unstubAllGlobals();vi.resetModules();});
it('preserves same-session non-secret drafts across locale restore and purges another identity',async()=>{
  const values=new Map<string,string>();
  const storage={get length(){return values.size;},key:(i:number)=>[...values.keys()][i]??null,getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>values.set(k,v),removeItem:(k:string)=>values.delete(k)};
  vi.stubGlobal('sessionStorage',storage); const window=new EventTarget();vi.stubGlobal('window',window);
  let purges=0;window.addEventListener('bt:access-change',()=>purges++);
  let state=await import('../shell/private-state');
  state.setAccessContext('owner-session-1',['buyer']); state.saveNonSecretDraft('owner-session-1','watch','blue dial');
  vi.resetModules(); state=await import('../shell/private-state'); // Document reload on locale change.
  state.setAccessContext('owner-session-1',['buyer']);
  expect(state.readNonSecretDraft('owner-session-1','watch')).toBe('blue dial');
  state.setAccessContext('other-session-2',['buyer']);
  expect(state.readNonSecretDraft('owner-session-1','watch')).toBeNull();
  expect([...values.keys()].some(k=>k.startsWith('bt-draft:'))).toBe(false);
  expect(()=>state.saveNonSecretDraft('owner-session-1','late','late write')).toThrow();
  expect(purges).toBe(2);
  vi.stubGlobal('sessionStorage',{getItem(){throw new Error('denied');},removeItem(){throw new Error('denied');}});
  state.setAccessContext(null);
  expect(purges).toBe(3); // Restricted storage must not prevent private-query invalidation.
});
