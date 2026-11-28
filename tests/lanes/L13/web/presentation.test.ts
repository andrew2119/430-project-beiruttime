import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {it,expect,vi} from 'vitest';
import {readQuoteSelection,rememberQuoteSelection,clearQuoteSelection} from '../../../../web/features/buy-now/quote-memory';
import Checkout from '../../../../web/features/buy-now/checkout';
import Withdrawals from '../../../../web/features/withdrawal/page';
import {LocaleContext} from '../../../../web/shell/locale-context';
import {ApiError} from '../../../../web/lib/api/client';
import registration from '../../../../web/registrations/L13';
import paymentEn from '../../../../web/features/payments/en.json';
import paymentAr from '../../../../web/features/payments/ar.json';
import withdrawalEn from '../../../../web/features/withdrawal/en.json';
import withdrawalAr from '../../../../web/features/withdrawal/ar.json';
import {connectedCopy} from '../../../../web/features/buy-now/connected-copy';
import {setAccessContext} from '../../../../web/shell/private-state';

for(const locale of ['en','ar'] as const){
  it(`${locale}: shared dashboard pages deny anonymous actions without raw-id forms`,()=>{
    const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
    client.getQueryCache().build(client,{queryKey:['l08-orders','restore']}).setState({status:'error',error:new ApiError(401,'unauthorized','proof'),fetchStatus:'idle'});
    for(const Page of [Checkout,Withdrawals]){
      const html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(LocaleContext.Provider,{value:locale},React.createElement(Page))));
      expect(html).toContain('pg-list-page');expect(html).toContain('hx-onpage');
      expect(html).toContain(`/${locale}/account?next=`);expect(html).not.toContain('<form');expect(html).not.toContain('<main');
      expect(html).not.toContain('name="watch_id"');expect(html).not.toContain('name="quote_id"');
    }
  });
}
it('retains only an owned opaque quote selection across locale reload, never another identity',()=>{
  const data=new Map<string,string>();
  vi.stubGlobal('sessionStorage',{getItem:(key:string)=>data.get(key)??null,setItem:(key:string,value:string)=>data.set(key,value),removeItem:(key:string)=>data.delete(key),get length(){return data.size;},key:(index:number)=>[...data.keys()][index]??null});
  vi.stubGlobal('window',{dispatchEvent:vi.fn()});
  const selection={owner:'owned-fingerprint',listingId:'00000000-0000-4000-8000-000000000001',quoteId:'00000000-0000-4000-8000-000000000002'};
  setAccessContext(selection.owner,['buyer']);rememberQuoteSelection(selection);expect(readQuoteSelection(selection.owner)).toEqual(selection);
  expect(readQuoteSelection('another-fingerprint')).toBeNull();
  setAccessContext('another-fingerprint',['buyer']);rememberQuoteSelection(selection);expect(readQuoteSelection(selection.owner)).toBeNull();
  setAccessContext(selection.owner,['buyer']);expect(readQuoteSelection(selection.owner)).toBeNull();
  rememberQuoteSelection(selection);clearQuoteSelection(selection.owner);expect(readQuoteSelection(selection.owner)).toBeNull();setAccessContext(null);expect(data.size).toBe(0);vi.unstubAllGlobals();
});
it('keeps complete EN/AR copy for payment, withdrawal and connected context',()=>{
  expect(Object.keys(paymentEn).sort()).toEqual(Object.keys(paymentAr).sort());
  expect(Object.keys(withdrawalEn).sort()).toEqual(Object.keys(withdrawalAr).sort());
  expect(Object.keys(connectedCopy.en).sort()).toEqual(Object.keys(connectedCopy.ar).sort());
});
it('adds only the new withdrawal URL and never duplicates checkout registration',()=>{
  expect(registration.routes.map(r=>r.path)).toEqual(['/seller/withdrawals']);
  expect(registration.routes[0].roles).not.toContain('buyer');
  expect(registration.gateway.find(r=>r.path==='/v1/orders/:id/journal')?.roles).toContain('buyer');
  expect(registration.slots[0].id).toBe('l13-auction-winner');
});
it('never exposes callbacks/internal operations through a browser gateway',()=>{
  expect(registration.gateway.every(r=>r.path.startsWith('/v1/'))).toBe(true);
  expect(registration.gateway.filter(r=>r.roles.includes('public' as never)).every(r=>r.methods.every(m=>m==='GET'))).toBe(true);
  expect(registration.gateway.some(r=>/callback|internal/.test(r.path))).toBe(false);
});
