import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import PrebidSlot from './prebid-slot';
import en from './en.json';
import ar from './ar.json';
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'current-buyer',principal:{roles:['buyer'],actor:{subject_id:'current-buyer'}}}),useSessionState:()=> 'authenticated',authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:()=>'/en/account'}));
function render(locale:'en'|'ar',operation:object|null,price:number|null=500000,standalone=true){
 const cache=new QueryClient();
 cache.setQueryData(['prebid-lots','listing'],{items:[{id:'auction',listing_id:'listing',currency:'USD',status:'live'}]});
 cache.setQueryData(['prebid-policy','auction'],{revision:4,mode:'prebid_reserved',buy_now_minor:price,frozen:true});
 cache.setQueryData(['my-prebid','current-buyer','auction'],{operation});
 return renderToStaticMarkup(createElement(QueryClientProvider,{client:cache},createElement(PrebidSlot,{locale,resourceId:'listing',standalone})));
}
it.each(['en','ar'] as const)('recovers the current buyer receipt without an in-memory command in %s',locale=>{
 const t=locale==='ar'?ar:en;
 const html=render(locale,{status:'succeeded',order_id:'own-order',quote_id:'own-quote'});
 expect(html).toContain(t.reserved);expect(html).toContain('/checkout?order_id=own-order&amp;quote_id=own-quote');expect(html).not.toContain(t.purchase);
});
it('keeps a different buyer on public held facts, without a private reference',()=>{
 const html=render('en',null);expect(html).toContain(en.held);expect(html).not.toContain('/checkout');expect(html).not.toContain('<form');
});
it('shows unavailable purchase context on the standalone dashboard while leaving absent watch actions hidden',()=>{
 expect(render('en',null,null)).toContain(en.disabled);expect(render('ar',null,null)).toContain(ar.disabled);
 expect(render('en',null,null,false)).toBe('');
});
