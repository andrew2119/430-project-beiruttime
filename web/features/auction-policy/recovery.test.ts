import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import PrebidSlot from './prebid-slot';
import en from './en.json';
import ar from './ar.json';
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'current-buyer',principal:{roles:['buyer'],actor:{subject_id:'current-buyer'}}}),authenticatedRequest:vi.fn()}));
function render(locale:'en'|'ar',operation:object|null){
 const cache=new QueryClient();
 cache.setQueryData(['prebid-lots','listing'],{items:[{id:'auction',listing_id:'listing',currency:'USD',status:'live'}]});
 cache.setQueryData(['my-prebid','current-buyer','auction'],{operation});
 return renderToStaticMarkup(createElement(QueryClientProvider,{client:cache},createElement(PrebidSlot,{locale,resourceId:'listing',standalone:true})));
}
it.each(['en','ar'] as const)('keeps historical pending outcomes in %s without purchase or checkout controls',locale=>{
 const t=locale==='ar'?ar:en;
 const html=render(locale,{status:'pending',order_id:'own-order',quote_id:'own-quote'});
 expect(html).toContain(t.pending);expect(html).toContain(t.excluded);expect(html).not.toContain('/checkout');expect(html).not.toContain('<form');expect(html).not.toContain('<button');
});
it('never lets a different buyer restore another historical reference',()=>{
 const html=render('en',null);expect(html).toContain(en.excluded);expect(html).not.toContain('own-order');expect(html).not.toContain('/checkout');
});
