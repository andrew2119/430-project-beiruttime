import {beforeEach,describe,expect,it,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {LocaleContext} from '@/shell/locale-context';
import BuyerWorkspace from './buyer-workspace';
const session=vi.hoisted(()=>({fingerprint:'owner-A' as string|null,signedIn:true,roles:['buyer']}));
vi.mock('./session',()=>({useBuyerSession:()=>session,authenticatedRequest:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
const activity={version:1,as_of:'2030-01-01T10:00:00Z',final_results_available:false,
  bids:{state:'available',next_cursor:null,items:[{auction_id:'auction-A',listing_id:'watch-A',status:'leading',current_price_minor:16000,currency:'USD',revision:1,ends_at:'2030-01-01T12:00:00Z',is_demo:true,private_maximum_minor:450000}]},
  reservations:{state:'available',next_cursor:null,items:[{reservation_id:'reservation-A',listing_id:'watch-B',state:'awaiting_payment',total_minor:24000,currency:'USD',revision:1,expires_at:'2030-01-01T12:00:00Z',is_demo:true,payment_available:false,delivery_available:false}]},
};
function render(client:QueryClient,locale:'en'|'ar'='en') {
  return renderToStaticMarkup(<LocaleContext value={locale}><QueryClientProvider client={client}><BuyerWorkspace/></QueryClientProvider></LocaleContext>);
}
beforeEach(()=>{session.fingerprint='owner-A';session.signedIn=true;session.roles=['buyer'];});
describe('buyer workspace private presentation',()=>{
  it('renders real DTO activity and honest payment limitations',()=>{
    const client=new QueryClient();client.setQueryData(['L06','buyer-workspace','owner-A'],activity);
    const html=render(client);
    expect(html).toContain('You are leading');expect(html).toContain('Awaiting payment');
    expect(html).toContain('This is not a paid order.');expect(html).toContain('Sample content');
    expect(html).not.toContain('memory-only');expect(html).not.toContain('private_maximum_minor');expect(html).not.toContain('450000');
  });
  it('uses the Arabic dictionary and safe locale links',()=>{
    const client=new QueryClient();client.setQueryData(['L06','buyer-workspace','owner-A'],activity);
    const html=render(client,'ar');
    expect(html).toContain('أنت المتصدر');expect(html).toContain('بانتظار الدفع');expect(html).toContain('/ar/watches/watch-A');
  });
  it('never reuses the previous account partition',()=>{
    const client=new QueryClient();client.setQueryData(['L06','buyer-workspace','owner-A'],activity);
    session.fingerprint='owner-B';
    const html=render(client);
    expect(html).not.toContain('auction-A');expect(html).not.toContain('reservation-A');expect(html).toContain('Loading');
  });
  it('purges private presentation on sign out even with cached answers',()=>{
    const client=new QueryClient();client.setQueryData(['L06','buyer-workspace','owner-A'],activity);
    session.signedIn=false;session.fingerprint=null;
    const html=render(client);
    expect(html).toContain('Sign in');expect(html).not.toContain('auction-A');expect(html).not.toContain('reservation-A');
  });
  it('labels a failed source separately and sends unconfirmed requests to Checkout',()=>{
    const client=new QueryClient();client.setQueryData(['L06','buyer-workspace','owner-A'],{
      ...activity,bids:{state:'unavailable',items:[],next_cursor:null},reservations:{...activity.reservations,items:[]},
    });
    const html=render(client);
    expect(html).toContain('Temporarily unavailable');expect(html).toContain('Pending or unconfirmed reservation requests stay in Checkout');
    expect(html).toContain('/en/checkout');
  });
});
