import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,it} from 'vitest';
import {LocaleContext} from '../../../../web/shell/locale-context';
import OrderDetail from '../../../../web/features/buy-now/order-detail';
import buyEn from '../../../../web/features/buy-now/en.json';
import buyAr from '../../../../web/features/buy-now/ar.json';
import {setSessionFixture} from '../web/session-fixture';
import en from '../../../../web/features/payments/en.json';
import ar from '../../../../web/features/payments/ar.json';
const id='00000000-0000-4000-8000-000000000001',owner='synthetic-checkout-scope';
afterEach(()=>setSessionFixture(null));
for(const locale of ['en','ar'] as const){
  for(const status of ['none','refund_pending','refunded','release_pending','released','reconciliation','unavailable'] as const){
    it(`${locale}: current ${status} overrides historical held payment`,()=>{
      setSessionFixture({access_fingerprint:owner,principal:{actor:{subject_id:id},permissions:[],organization_grants:[]}});
      const t=locale==='ar'?ar:en;
      const client=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false}}});
      client.setQueryData(['l13-checkout',owner,id],{
        order:{id,revision:3,state:'paid_held',order_kind:'sale',currency:'USD',total_minor:515000,deadline:null,notified_at:null,payment_method:null},
        financial_readiness:status==='unavailable'?undefined:{schema_version:3,order_id:id,revision:5,state:status==='none'?'paid_held':'pending',held_minor:0,reserved_minor:0,movement_status:status},
        quote:null,attempts:[{id,reference:'SIM-'+id,state:'confirmed'}],simulated:true,payable:false,server_time:'2026-11-16T12:01:00Z',method_deadlines:{card:null,whish:null,omt:null},
      });
      client.setQueryData(['l08-order',owner,id,null],{order:{id,buyer_id:id,revision:3,state:'paid_held',currency:'USD',total_minor:515000},history:[]});
      const html=renderToStaticMarkup(<QueryClientProvider client={client}><LocaleContext.Provider value={locale}><OrderDetail id={id}/></LocaleContext.Provider></QueryClientProvider>);
      expect(html).toContain(status==='none'?t.paid:status==='unavailable'?t.financialUnavailable:t[status]);
      if(status!=='none')expect(html).not.toContain(t.paid);
      expect(html).toContain(t.confirmed);
      expect(html).not.toContain((locale==='ar'?buyAr:buyEn).paid_held);
      expect(html).not.toContain(t.start);
      expect(html).not.toContain(t.pay);
    });
  }
}
