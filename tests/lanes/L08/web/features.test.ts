import {describe,it,expect} from 'vitest';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ApiError} from '../../../../web/lib/api/client';
import Checkout from '../../../../web/features/buy-now/checkout';
import RequestDrafts from '../../../../web/features/request-drafts/request-drafts';
import {LocaleContext} from '../../../../web/shell/locale-context';
import {recall,remember,purge,draftMemoryEpoch} from '../../../../web/features/request-drafts/memory';
import {recallReservation,rememberReservation,purgeReservation,reservationMemoryEpoch} from '../../../../web/features/buy-now/memory';
import {canonicalReference,uuid,requireAcknowledgedOperation,validatedReservation} from '../../../../web/features/buy-now/copy';
import checkoutEn from '../../../../web/features/buy-now/en.json';
import checkoutAr from '../../../../web/features/buy-now/ar.json';
import draftEn from '../../../../web/features/request-drafts/en.json';
import draftAr from '../../../../web/features/request-drafts/ar.json';
import registration from '../../../../web/registrations/L08';
import {formatQuotedMoney} from '../../../../web/features/buy-now/money';
import sampleReservation from '../../../../packages/contracts-orders/allocation/fixtures/reservation.v1.json';
import type {AllocationOperation} from '../../../../packages/contracts-orders/allocation';

for(const locale of ['en','ar'] as const){
  describe(locale,()=>{
    it('shows sign in, never fake checkout or draft authority',()=>{
      const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
      for(const queryKey of [['l08-orders','restore'],['l08-drafts','restore'],['l08-draft-boundary']])client.getQueryCache().build(client,{queryKey}).setState({status:'error',error:new ApiError(401,'unauthorized','proof'),fetchStatus:'idle'});
      const checkout=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(LocaleContext.Provider,{value:locale},React.createElement(Checkout))));
      const draft=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(LocaleContext.Provider,{value:locale},React.createElement(RequestDrafts))));
      expect(checkout).toContain(`/${locale}/account?next=%2Fcheckout`);
      expect(draft).toContain(`/${locale}/account?next=%2Fcustom-requests`);
      expect(checkout).not.toContain('<form');expect(draft).not.toContain('<form');
    });
  });
}
it('never treats an HTTP-200 denial or pending operation as a successful physical fact',()=>{
  expect(()=>requireAcknowledgedOperation({id:'operation',request_id:'proof',status:'denied',code:'stale_revision'})).toThrow('stale_revision');
  try{requireAcknowledgedOperation({id:'operation',request_id:'proof',status:'pending'});expect.unreachable();}catch(error){expect(error).toBeInstanceOf(ApiError);expect((error as ApiError).status).toBe(503);}
  const success={id:'operation',request_id:'proof',status:'succeeded' as const};expect(requireAcknowledgedOperation(success)).toBe(success);
});
it('binds reservation acknowledgements to the actual buyer, watch and uncharged state',()=>{
  const value=sampleReservation as AllocationOperation,watch=value.order!.watch_id,buyer=value.order!.buyer_id;
  expect(validatedReservation(value,watch,buyer)).toBe(value);
  const legacy=structuredClone(value);Reflect.deleteProperty(legacy.order!,'is_demo');Reflect.deleteProperty(legacy.order!,'listing_id');
  expect(validatedReservation(legacy,watch,buyer)).toBe(legacy);
  expect(()=>validatedReservation(value,watch,'another-buyer')).toThrow('invalid_allocation_response');
  for(const changed of [{state:'paid'},{payment_authority:true},{total_minor:1.5}]){
    const malformed=structuredClone(value);Object.assign(malformed.order!,changed);
    expect(()=>validatedReservation(malformed,watch,buyer)).toThrow('invalid_allocation_response');
  }
  const denied={id:value.id,request_id:value.request_id,status:'denied' as const,payment_authority:false as const};
  expect(validatedReservation(denied,watch,buyer)).toBe(denied);
});
it('renders the exact quoted cents at the safe-integer boundary without binary rounding',()=>{
  expect(formatQuotedMoney(8999999999999999,'USD','en')).toBe('$89,999,999,999,999.99');
  expect(formatQuotedMoney(1,'USD','en')).toBe('$0.01');
  expect(formatQuotedMoney(101,'USD','ar')).toContain('١٫٠١');
  expect(()=>formatQuotedMoney(1.5,'USD','en')).toThrow(RangeError);
});
it('normalizes Arabic and Persian digits only for opaque command references',()=>{
  const reference=canonicalReference('  A٠٠٠٠٠٠٠-۰۰۰۰-۴۰۰۰-۸۰۰۰-۰۰۰۰۰۰۰۰۰۰۰۱  ');
  expect(reference).toBe('a0000000-0000-4000-8000-000000000001');expect(uuid.test(reference)).toBe(true);
});
it('keeps equal EN/AR key coverage',()=>{expect(Object.keys(checkoutEn).sort()).toEqual(Object.keys(checkoutAr).sort());expect(Object.keys(draftEn).sort()).toEqual(Object.keys(draftAr).sort());});
it('exposes no internal service mutation through the public gateway',()=>{
  expect(registration.gateway.some(route=>route.path.startsWith('/internal/'))).toBe(false);
  expect(registration.gateway.filter(route=>route.roles.includes('public' as never)).every(route=>route.methods.every(method=>method==='GET'))).toBe(true);
});
it('partitions and purges memory-only neutral draft intent',()=>{
  purge();const form={brand_id:null,kind:'service' as const,watch_context:'owned_watch' as const,watch_reference:'Sample watch',scope_intent:'Assessment',notes:'Private note',options:{}};
  const before=draftMemoryEpoch();remember({owner:'one',id:null,revision:0,form},before);expect(recall('one')?.form.notes).toBe('Private note');
  expect(recall('two')).toBeNull();expect(recall('one')).toBeNull();purge();
  remember({owner:'one',id:null,revision:0,form},before);expect(recall('one')).toBeNull();
});
it('retains one uncertain reservation key across same-profile locale navigation only',()=>{
  const pending={key:'stable-operation',body:{watch_id:'watch',quote_id:'quote',expected_revision:1}};
  const before=reservationMemoryEpoch();rememberReservation({owner:'one',watch:'watch',quote:'quote',checked:'watch',pending},before);
  expect(recallReservation('one')?.pending).toEqual(pending);
  expect(recallReservation('two')).toBeNull();expect(recallReservation('one')).toBeNull();purgeReservation();
  rememberReservation({owner:'one',watch:'watch',quote:'quote',checked:'watch',pending},before);expect(recallReservation('one')).toBeNull();
});
