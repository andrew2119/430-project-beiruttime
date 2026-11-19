import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import source from '../../../../packages/contracts-identity/public-profile/fixtures/success-response.v1.json';
import { sellerPage } from '../../../../web/features/seller-profile/page';
const mounted=vi.hoisted(()=>({locale:'en',page:1,query:{data:undefined as unknown,isPending:false,isFetching:false,isError:false,error:undefined as unknown,refetch:vi.fn()}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>mounted.locale}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>mounted.query}));
vi.mock('@/features/seller-profile/read',()=>({useSellerRefresh:()=>{},useSellerRead:(_id:string,page:number)=>{mounted.page=page;return mounted.query;}}));
import SellerProfile from '../../../../web/features/seller-profile/view';

import { Element, DocumentHost } from './native-host';
afterEach(()=>vi.unstubAllGlobals());
it.each(['en','ar'])('retains focused pagination and retry nodes through mounted reads in %s',async locale=>{
 mounted.locale=locale;
 const document=new DocumentHost();
 vi.stubGlobal('document',document);vi.stubGlobal('window',document.defaultView);
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
 const container=new Element('div',document);
 const root=createRoot(container as unknown as HTMLElement);
 mounted.query={...mounted.query,data:{...source,listings:{...source.listings,total:40}},isPending:false,isFetching:false,isError:false};
 await act(async()=>root.render(<SellerProfile id="seller-1"/>));
 const next=container.buttons()[2];next.focus();
 await act(async()=>next.click());
 expect(mounted.page).toBe(2);
 const address=new URL(document.defaultView.location.href);
 expect(address.searchParams.get('page')).toBe('2');
 expect(address.searchParams.get('filter')).toBe('watch');
 expect(address.hash).toBe('#listings');
 mounted.query={...mounted.query,data:undefined,isPending:true,isFetching:true};
 await act(async()=>root.render(<SellerProfile id="seller-1"/>));
 expect(container.buttons()[2]).toBe(next);expect(document.activeElement).toBe(next);
 expect(next.attributes.get('aria-disabled')).toBe('true');
 mounted.query={...mounted.query,data:{...source,listings:{...source.listings,page:2}},isPending:false,isFetching:false};
 await act(async()=>root.render(<SellerProfile id="seller-1"/>));
 expect(document.activeElement).toBe(next);expect(container.buttons()[2]).toBe(next);
 const retry=container.buttons()[0];retry.focus();mounted.query.refetch.mockClear();await act(async()=>retry.click());
 expect(mounted.query.refetch).toHaveBeenCalledOnce();
 mounted.query={...mounted.query,data:undefined,isPending:true,isFetching:true};
 await act(async()=>root.render(<SellerProfile id="seller-1"/>));
 expect(document.activeElement).toBe(retry);expect(container.buttons()[0]).toBe(retry);
 mounted.query={...mounted.query,isPending:false,isFetching:false,isError:true};
 await act(async()=>root.render(<SellerProfile id="seller-1"/>));
 expect(document.activeElement).toBe(retry);expect(container.buttons()[0]).toBe(retry);
 await act(async()=>root.unmount());
 const reloaded=createRoot(container as unknown as HTMLElement);
 await act(async()=>reloaded.render(<SellerProfile id="seller-1" initialPage={sellerPage(address.searchParams.get('page')??undefined)}/>));
 expect(mounted.page).toBe(2);
 await act(async()=>reloaded.unmount());
});

it.each([undefined,[],['2','3'],'0','-1','1.5','100001','0002',''])('bounds public page criteria %s',value=>{
 expect(sellerPage(value)).toBe(1);
});
it.each(['1','2','100000'])('accepts public page criteria %s',value=>{
 expect(sellerPage(value)).toBe(Number(value));
});
