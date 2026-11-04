import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LocaleContext } from '@/shell/locale-context';
import PricingPage from '../pricing/quotes';
import BuyingPage from '../pricing/buying';
import InboxPage from '../inbox/page';
import Checkout from '../buy-now/checkout';
import OrderDetail from '../buy-now/order-detail';
import { Select } from '@beirut-time/ui';

const session=vi.hoisted(()=>({access_fingerprint:'visual-owner',principal:{actor:{subject_id:'00000000-0000-4000-8000-000000000001'},permissions:['orders.intake','orders.manage'],organization_grants:[]}}));
vi.mock('@/features/identity/session',()=>({useSession:()=>session,authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()})}));
const id='00000000-0000-4000-8000-000000000005';
const order={id,watch_id:'00000000-0000-4000-8000-000000000006',quote_id:'00000000-0000-4000-8000-000000000004',organization_id:null,state:'awaiting_payment',revision:1,currency:'USD',total_minor:515000,deadline:'2099-01-01T00:00:00Z',is_demo:true};
let client:QueryClient;
beforeEach(()=>{client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});});
function render(children:React.ReactNode,locale:'en'|'ar'='en') {
  return renderToStaticMarkup(<LocaleContext value={locale}><QueryClientProvider client={client}>{children}</QueryClientProvider></LocaleContext>);
}
describe('Creator Pipeline buyer-area presentation contract',()=>{
  it.each(['en','ar'] as const)('uses shared page headers, true navigation links and menu-backed selects in %s',locale=>{
    client.setQueryData(['l07','visual-owner','quotes'],{items:[]});
    const html=render(<PricingPage/>,locale);
    expect(html).toContain('hx-head');expect(html).toContain('data-opt="A"');
    expect(html).toContain(`href="/${locale}/inbox"`);expect(html).toContain('aria-current="page"');
    expect(html).toContain('ui-select');expect(html).toContain('aria-haspopup="menu"');
    expect(html).not.toContain('<select');expect(html).toContain('pg-chonk');
    expect(html).toContain('buyer-section-state');
  });
  it('keeps the controlled currency Select correct for USD → LBP → USD switch-back',()=>{
    const onValueChange=vi.fn();
    for(const value of ['USD','LBP','USD']) {
      const html=render(<Select aria-label="Currency" value={value} onValueChange={onValueChange} options={[{value:'USD',label:'USD'},{value:'LBP',label:'LBP'}]}/>);
      expect(html).toContain(`data-value="${value}"`);
      expect(html).toContain(`class="ui-select-value">${value}</span>`);
      expect(html).toContain('aria-haspopup="menu"');
    }
    expect(onValueChange).not.toHaveBeenCalled();
  });
  it('retains non-binding readiness, disabled payment and offer-send controls',()=>{
    client.setQueryData(['l07','visual-owner','readiness',{reservation:'',quote:''}],{reservation:{status:'not_selected'},quote:{status:'not_selected'},routes:[],drafts:[{id:'draft-A',subject_id:id,subject_revision:1,currency:'USD',amount_minor:50000,revision:1}]});
    const html=render(<BuyingPage/>);
    expect(html).toContain('pg-list-item');expect(html).toContain('disabled=""');
    expect(html).toContain('Send offer');
    expect(html).toContain('ui-select');
  });
  it.each(['en','ar'] as const)('renders the CP switch, unread dot and independent notice actions in %s',locale=>{
    client.setQueryData(['l07','visual-owner','notice-preferences'],{optional_enabled:true,revision:2});
    client.setQueryData(['l07','visual-owner','inbox'],{pages:[{items:[{id:'notice-A',kind:'outbid',required:true,read_at:null,event_time:'2030-01-01T00:00:00Z',resource_id:id,resource_revision:1,sample:true,destination:'/buyer'}],unread_count:1,next_cursor:null}],pageParams:[null]});
    const html=render(<InboxPage/>,locale);
    expect(html).toContain('role="switch"');expect(html).toContain('aria-checked="true"');
    expect(html).toContain('l07-inbox-dot');expect(html).toContain('pg-list-item');
    expect(html).toContain('data-read="false"');expect(html).not.toContain('type="checkbox"');
  });
  it('keeps real order links inside the shared checkout card/list composition',()=>{
    client.setQueryData(['l08-orders','visual-owner'],{items:[order]});
    const html=render(<Checkout/>);
    expect(html).toContain('hx-head');expect(html).toContain('ui-card');expect(html).toContain('pg-list-item');
    expect(html).toContain(`/en/checkout/${id}`);expect(html).toContain('name="watch_id"');
  });
  it('retains permission-gated hold and intake forms with the shared textarea',()=>{
    client.setQueryData(['l08-order','visual-owner',id,null],{order,history:[{action:'reserve',revision:1,occurred_at:'2030-01-01T00:00:00Z'}]});
    const html=render(<OrderDetail id={id}/>);
    expect(html).toContain('name="reason"');expect(html).toContain('name="actual_watch"');
    expect(html).toContain('ui-textarea');expect(html).toContain('pg-list-item');
    expect(html).toContain('<bdi dir="ltr">');
  });
});
