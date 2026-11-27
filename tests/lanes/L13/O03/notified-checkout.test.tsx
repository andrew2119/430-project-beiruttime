import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it} from 'vitest';
import {LocaleContext} from '../../../../web/shell/locale-context';
import CheckoutPayment from '../../../../web/features/payments/checkout-payment';
import {setSessionFixture} from '../web/session-fixture';
import {financialReadinessFixture} from './readiness-fixture';
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
        financial_readiness:financialReadinessFixture(id),
        order:{id,revision:1,state:notified?'awaiting_payment':'awaiting_notification',currency:'USD',
          total_minor:515000,deadline:notified?'2026-11-18T12:00:00Z':null,notified_at:notifiedAt,initiation_extended_until:null,payment_method:null},
        quote:{id,revision:2,currency:'USD',price_minor:500000,buyer_fee_minor:15000,shipping_minor:0,tax_minor:0,payable_minor:515000,sample:!notified,reviewed_at:null},
        attempts:[],simulated:true,payable:notified,server_time:'2026-11-16T12:01:00Z',
        method_deadlines:{card:notified?'2026-11-17T12:00:00Z':null,whish:notified?'2026-11-18T12:00:00Z':null,omt:notified?'2026-11-18T12:00:00Z':null},
      });
      const html=renderToStaticMarkup(<QueryClientProvider client={client}><LocaleContext.Provider value={locale}><CheckoutPayment orderId={id} onRefresh={()=>{}}/></LocaleContext.Provider></QueryClientProvider>);
      expect(html).toContain(t.feeTerms);
      expect(html).toContain(t.clockTerms);
      if(notified)expect(html).not.toContain(t.sample);
      else expect(html).toContain(t.sample);
      expect(html).not.toContain(locale==='ar'?'محتوى ساعة':'Sample watch content');
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
  for(const pricing of ['pending','reconciliation']){
    it(`${locale}: pricing ${pricing} never claims payment confirmation`,()=>{
      setSessionFixture({access_fingerprint:owner,principal:{actor:{subject_id:id},permissions:[],organization_grants:[]}});
      const t=locale==='ar'?ar:en;
      const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
      client.setQueryData(['l13-checkout',owner,id],{
        financial_readiness:financialReadinessFixture(id),
        order:{id,revision:1,state:'awaiting_payment',order_kind:'sale',currency:'USD',total_minor:515000,
          deadline:'2026-11-18T12:00:00Z',notified_at:'2026-11-16T12:00:00Z',initiation_extended_until:null,payment_method:null},
        quote:{id,revision:2,currency:'USD',price_minor:500000,buyer_fee_minor:15000,shipping_minor:0,tax_minor:0,
          payable_minor:515000,sample:false,reviewed_at:'2026-11-16T12:00:00Z'},
        attempts:[],pricing_commit_state:pricing,simulated:true,payable:pricing==='pending',server_time:'2026-11-16T12:01:00Z',
        method_deadlines:{card:'2026-11-17T12:00:00Z',whish:'2026-11-18T12:00:00Z',omt:'2026-11-18T12:00:00Z'},
      });
      const html=renderToStaticMarkup(<QueryClientProvider client={client}><LocaleContext.Provider value={locale}><CheckoutPayment orderId={id} onRefresh={()=>{}}/></LocaleContext.Provider></QueryClientProvider>);
      expect(html).toContain(pricing==='pending'?t.sourceSync:t.sourceHold);
      expect(html).not.toContain(t.paid);
    });
  }
}

for(const locale of ['en','ar'] as const){
  for(const state of ['awaiting_payment','paid_held']){
    for(const currentFunds of [false,true]){
    it(`${locale}: ${state}, current funds ${currentFunds}, keeps job principal and business fee separate`,()=>{
      setSessionFixture({access_fingerprint:owner,principal:{actor:{subject_id:id},permissions:[],organization_grants:[]}});
      const t=locale==='ar'?ar:en;
      const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
      client.setQueryData(['l13-checkout',owner,id],{
        financial_readiness:currentFunds?financialReadinessFixture(id,state==='paid_held'?500000:0):undefined,
        order:{id,revision:1,state,order_kind:'service_job',currency:'USD',total_minor:500000,
          deadline:'2026-11-18T12:00:00Z',notified_at:'2026-11-16T12:00:00Z',initiation_extended_until:null,payment_method:null},
        quote:{id,revision:2,currency:'USD',price_minor:500000,buyer_fee_minor:0,shipping_minor:0,tax_minor:0,
          payable_minor:500000,return_fee_minor:2000,sample:false,reviewed_at:'2026-11-16T12:00:00Z'},
        attempts:[],simulated:true,payable:state==='awaiting_payment',server_time:'2026-11-16T12:01:00Z',
        method_deadlines:{card:'2026-11-17T12:00:00Z',whish:'2026-11-18T12:00:00Z',omt:'2026-11-18T12:00:00Z'},
      });
      const html=renderToStaticMarkup(<QueryClientProvider client={client}><LocaleContext.Provider value={locale}><CheckoutPayment orderId={id} onRefresh={()=>{}}/></LocaleContext.Provider></QueryClientProvider>);
      expect(html).toContain(t.jobFeeTerms);
      expect(html).toContain(t.jobAmount);
      expect(html).toContain(t.conditionalReturn);
      expect(html).not.toContain(t.feeTerms);
      expect(html).not.toContain('>'+t.shipping+'<');
      if(currentFunds&&state==='paid_held')expect(html).toContain(t.jobHeld);
      if(!currentFunds){
        expect(html).toContain(t.financialUnavailable);
        for(const text of [t.jobHeld,t.paid,t.start,t.pay])expect(html).not.toContain(text);
      }
    });
  }
}
}

for(const locale of ['en','ar'] as const){
  for(const state of ['paid_held','awaiting_payment','payment_unknown']){
    it(`${locale}: failed refresh hides cached ${state} claims and controls`,()=>{
      setSessionFixture({access_fingerprint:owner,principal:{actor:{subject_id:id},permissions:[],organization_grants:[]}});
      const t=locale==='ar'?ar:en;
      const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
      const key=['l13-checkout',owner,id];
      client.setQueryData(key,{
        financial_readiness:financialReadinessFixture(id,state==='paid_held'?515000:0),
        order:{id,state,order_kind:'sale',currency:'USD',total_minor:515000},
        quote:{id,revision:2,currency:'USD',price_minor:500000,buyer_fee_minor:15000,shipping_minor:0,tax_minor:0,payable_minor:515000},
        attempts:state==='payment_unknown'?[{id,reference:'SIM-'+id,state:'pending'}]:[],
        payable:true,method_deadlines:{card:'2026-11-18T12:00:00Z'},server_time:'2026-11-16T12:00:00Z',
      });
      client.getQueryCache().find({queryKey:key})!.setState({status:'error',error:new Error('Unavailable')});
      const html=renderToStaticMarkup(<QueryClientProvider client={client}><LocaleContext.Provider value={locale}><CheckoutPayment orderId={id} onRefresh={()=>{}}/></LocaleContext.Provider></QueryClientProvider>);
      expect(html).toContain(t.financialUnavailable);
      for(const text of [t.paid,t.jobHeld,t.start,t.pay,t.decline,t.leavePending])expect(html).not.toContain(text);
    });
  }
}
