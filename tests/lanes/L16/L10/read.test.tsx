import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import source from '../../../../packages/contracts-identity/public-profile/fixtures/success-response.v1.json';
import { Element, DocumentHost } from './native-host';
import { QueryClientProvider } from '@tanstack/react-query';
import { createReadScope } from '../../../../web/lib/page-speed/scope';
const shared=vi.hoisted(()=>({scope:null as unknown}));
vi.mock('@/lib/page-speed/provider',()=>({usePageReadScope:()=>shared.scope}));
const transport=vi.hoisted(()=>({request:vi.fn(),scope:'visitor'}));
vi.mock('@/lib/api/client',()=>({request:transport.request}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:transport.scope})}));
import { useSellerRead as useSellerQuestion, useSellerRefresh } from '../../../../web/features/seller-profile/read';
import { usePageRead } from '../../../../web/lib/page-speed/read';
function useSellerRead(id:string,page:number) {
 const read=useSellerQuestion(id,page);
 const query=usePageRead(read);
 useSellerRefresh(query.refetch,read!==null);
 return {...query,refetch:()=>{void query.refetch();}};
}
afterEach(()=>vi.unstubAllGlobals());
it('keeps the same pending read across an in-place locale change and retries, then clears changed scope',async()=>{
 const scope=createReadScope('test-public');
 shared.scope=scope;
 const document=new DocumentHost();
 const listeners=new Map<string,()=>void>();
 vi.stubGlobal('document',document);
 vi.stubGlobal('window',{...document.defaultView,addEventListener:(name:string,callback:()=>void)=>listeners.set(name,callback),removeEventListener:(name:string)=>listeners.delete(name)});
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
 const replies:((value:unknown)=>void)[]=[];
 transport.request.mockReset();
 transport.request.mockImplementation(()=>new Promise(resolve=>replies.push(resolve)));
 let current:ReturnType<typeof useSellerRead>;
 function Read({locale}:{locale:string}) {
  const query=useSellerRead('seller-1',1);
  useEffect(()=>{current=query;},[query]);
  return <p lang={locale}>{query.data?.identity?.name}</p>;
 }
 const root=createRoot(new Element('div',document) as unknown as HTMLElement);
 await act(async()=>root.render(<QueryClientProvider client={scope.client}><Read locale="en"/></QueryClientProvider>));
 const [path,options]=transport.request.mock.calls[0];
 const operation=new URL(path,'https://example.test').searchParams.get('operation_id');
 expect(operation).toMatch(/^[a-zA-Z0-9-]{1,80}$/);
 await act(async()=>root.render(<QueryClientProvider client={scope.client}><Read locale="ar"/></QueryClientProvider>));
 expect(transport.request).toHaveBeenCalledTimes(1);
 expect(new URL(window.location.href).searchParams.get('profile_read')).toBe(operation);
 expect(options.signal.aborted).toBe(false);
 expect(current!.isPending).toBe(true);
 await act(async()=>{replies[0]({...source,operation_id:operation});await new Promise(resolve=>setTimeout(resolve,10));});
 expect(current!.data?.operation_id).toBe(operation);
 await act(async()=>{current!.refetch();await new Promise(resolve=>setTimeout(resolve,10));});
 expect(transport.request.mock.calls[1][0]).toBe(path);
 expect(current!.isFetching).toBe(true);
 await act(async()=>{replies[1]({...source,operation_id:'wrong-reference'});await new Promise(resolve=>setTimeout(resolve,10));});
 expect(current!.isError).toBe(true);
 await act(async()=>{current!.refetch();await new Promise(resolve=>setTimeout(resolve,10));});
 expect(transport.request.mock.calls[2][0]).toBe(path);
 transport.scope='changed';
 await act(async()=>root.render(<QueryClientProvider client={scope.client}><Read locale="ar"/></QueryClientProvider>));
 expect(transport.request.mock.calls[2][1].signal.aborted).toBe(true);
 expect(transport.request.mock.calls[3][0]).not.toBe(path);
 await act(async()=>replies[2]({...source,operation_id:operation}));
 expect(current!.data).toBeUndefined();
 await act(async()=>root.unmount());
 scope.clear();
 expect(listeners.size).toBe(0);
});

it('reuses the public read reference after a document remount',async()=>{
 const scope=createReadScope('test-public');
 shared.scope=scope;
 const document=new DocumentHost();
 document.defaultView.location.href='https://example.test/ar/sellers/seller-1?profile_read=read-retained';
 vi.stubGlobal('document',document);
 vi.stubGlobal('window',{...document.defaultView,addEventListener:()=>{},removeEventListener:()=>{}});
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
 transport.request.mockReset();
 transport.request.mockImplementation(()=>new Promise(()=>{}));
 function Read() {useSellerRead('seller-1',1);return null;}
 for (let visit=0;visit<2;visit++) {
  const root=createRoot(new Element('div',document) as unknown as HTMLElement);
  await act(async()=>root.render(<QueryClientProvider client={scope.client}><Read/></QueryClientProvider>));
  expect(new URL(transport.request.mock.calls[visit][0],'https://example.test').searchParams.get('operation_id')).toBe('read-retained');
  await act(async()=>root.unmount());
 }
 scope.clear();
});
