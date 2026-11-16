import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it} from 'vitest';
import {LocaleContext} from '../../../../web/shell/locale-context';
import CheckoutPayment from '../../../../web/features/payments/checkout-payment';
import WinnerSlot from '../../../../web/features/buy-now/winner-slot';
import {validatedReservation} from '../../../../web/features/buy-now/copy';
import type {AllocationOperation} from '../../../../packages/contracts-orders/allocation';
import {setSessionFixture} from './session-fixture';
import en from '../../../../web/features/payments/en.json';
import ar from '../../../../web/features/payments/ar.json';

const id='00000000-0000-4000-8000-000000000001';
const owner='synthetic-checkout-scope';
afterEach(()=>setSessionFixture(null));

for(const locale of ['en','ar'] as const){
  for(const notified of [false,true]){
    it(`${locale}: renders ${notified?'original notice deadline':'notification pending without hidden deadline'}`,()=>{
      setSessionFixture({access_fingerprint:owner,principal:{actor:{subject_id:id},permissions:[],organization_grants:[]}});
      const t=locale==='ar'?ar:en;
      const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
      const notifiedAt=notified?'2026-11-16T12:00:00Z':null;
      client.setQueryData(['l13-checkout',owner,id],{
        order:{id,revision:1,state:notified?'awaiting_payment':'awaiting_notification',currency:'USD',
          total_minor:515000,deadline:notified?'2026-11-18T12:00:00Z':null,notified_at:notifiedAt,initiation_extended_until:null,payment_method:null},
        quote:{id,revision:2,currency:'USD',price_minor:500000,buyer_fee_minor:15000,shipping_minor:0,tax_minor:0,payable_minor:515000,sample:false,reviewed_at:null},
        attempts:[],simulated:true,payable:notified,server_time:'2026-11-16T12:01:00Z',
        method_deadlines:{card:notified?'2026-11-17T12:00:00Z':null,whish:notified?'2026-11-18T12:00:00Z':null,omt:notified?'2026-11-18T12:00:00Z':null},
      });
      const html=renderToStaticMarkup(<QueryClientProvider client={client}><LocaleContext.Provider value={locale}><CheckoutPayment orderId={id} onRefresh={()=>{}}/></LocaleContext.Provider></QueryClientProvider>);
      expect(html).toContain(t.feeTerms);
      expect(html).toContain(t.clockTerms);
      expect(html).not.toContain(t.sample);
      expect(html).not.toContain('1970');
      if(notified){
        expect(html).toContain('dateTime="2026-11-16T12:00:00Z"');
        expect(html).toContain('dateTime="2026-11-17T12:00:00Z"');
        expect(html).not.toContain(t.notificationPending);
      }else{
        expect(html).toContain(t.notificationPending);
        expect(html).not.toContain('dateTime=');
      }
    });
  }
}

for(const locale of ['en','ar'] as const){
  it(`${locale}: distinguishes fixed-end legacy review without a new payment link`,()=>{
    const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
    client.setQueryData(['l13-close-lot',id],{items:[{id}]});
    client.setQueryData(['l13-close',id],{status:'ended_legacy_review'});
    const html=renderToStaticMarkup(<QueryClientProvider client={client}><WinnerSlot resourceId={id} locale={locale}/></QueryClientProvider>);
    expect(html).toContain(locale==='ar'?'نتيجة الشراء السابق':'legacy purchase outcome');
    expect(html).not.toContain('/checkout/');
  });
}

it('accepts notification-pending reservation only with no hidden clock and USD economics',()=>{
  const value:AllocationOperation={id,request_id:'synthetic',resource_id:id,status:'succeeded',order:{
    id,watch_id:id,quote_id:id,buyer_id:id,seller_id:id,organization_id:null,state:'awaiting_notification',
    revision:1,currency:'USD',total_minor:515000,deadline:null,payment_authority:false,
  }};
  expect(validatedReservation(value,id,id)).toBe(value);
  for(const change of [{deadline:'2026-11-18T12:00:00Z'},{currency:'LBP'},{notified_at:'2026-11-16T12:00:00Z'}]){
    expect(()=>validatedReservation({...value,order:{...value.order!,...change} as typeof value.order},id,id)).toThrow();
  }
});
