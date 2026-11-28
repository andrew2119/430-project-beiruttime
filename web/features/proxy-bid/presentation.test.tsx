import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LocaleContext } from '@/shell/locale-context';
import { optionsFor } from '@/lib/page-speed/definition';
import { PageReadProvider, usePageReadScope } from '@/lib/page-speed/provider';
import type { Inbox, Readiness } from '@contracts/contracts-comms/inbox';
import type { Availability } from '@contracts/contracts-orders/allocation';
import { inboxRead, noticePreferencesRead } from '../inbox/reads';
import inboxEn from '../inbox/en.json';
import inboxAr from '../inbox/ar.json';
import buyingCopy from '../pricing/en.json';
import { connectedCopy } from '../buy-now/connected-copy';
import PricingPage from '../pricing/quotes';
import BuyingPage from '../pricing/buying';
import InboxPage from '../inbox/page';
import Checkout from '../buy-now/checkout';
import OrderDetail from '../buy-now/order-detail';
import BuyerWorkspace from './buyer-workspace';
import contracts from './delivery-contract.json';
import { activityRead } from './activity-read';
import { BuyerActions } from './buyer-actions';
import { Select } from '@beirut-time/ui';

// Server rendering cannot run the mounted authorization refresh. The workspace
// cases supply its settled answer through the shared observer; every other case
// reads the observer unchanged.
const settled=vi.hoisted(()=>({answer:false}));
vi.mock('@/lib/page-speed/read',async load=>{
  const shared=await load<typeof import('@/lib/page-speed/read')>();
  return {...shared,usePageRead:(...args:Parameters<typeof shared.usePageRead>)=>{
    const answer=shared.usePageRead(...args);
    return settled.answer?{...answer,isFetchedAfterMount:true,isFetching:false}:answer;
  }};
});
const session=vi.hoisted(()=>({access_fingerprint:'visual-owner',principal:{actor:{subject_id:'00000000-0000-4000-8000-000000000001'},roles:['buyer'],permissions:['orders.intake','orders.manage'],organization_grants:[]}}));
vi.mock('@/features/identity/session',()=>({useSession:()=>session,useSessionState:()=>'authenticated',authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:session.access_fingerprint,roles:['buyer']})}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn(),refresh:vi.fn()}),usePathname:()=>'/en/buyer'}));
const id='00000000-0000-4000-8000-000000000005';
const order={id,watch_id:'00000000-0000-4000-8000-000000000006',quote_id:'00000000-0000-4000-8000-000000000004',organization_id:null,state:'awaiting_payment',revision:1,currency:'USD',total_minor:515000,deadline:'2099-01-01T00:00:00Z',is_demo:true};
let client:QueryClient;
beforeEach(()=>{client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});settled.answer=false;});
function render(children:React.ReactNode,locale:'en'|'ar'='en') {
  return renderToStaticMarkup(<LocaleContext value={locale}><QueryClientProvider client={client}>{children}</QueryClientProvider></LocaleContext>);
}
function button(html:string,label:string) {
  const match=html.match(/<button\b[^>]*>.*?<\/button>/gs)?.find(node=>node.includes(`>${label}<`));
  expect(match,`Expected button: ${label}`).toBeDefined();
  return match!;
}
function InboxFixture({notices}:{notices:Inbox}) {
  const scope=usePageReadScope(),owner=session.access_fingerprint;
  scope.client.setQueryData(optionsFor(scope,inboxRead(owner,null)).queryKey,notices);
  scope.client.setQueryData(optionsFor(scope,noticePreferencesRead(owner)).queryKey,{optional_enabled:true,revision:2});
  return <InboxPage/>;
}
// The workspace's unread notices are seeded through the inbox page's own read, and its
// leading activity through the workspace's read, both in the shared page scope.
function WorkspaceFixture({unread,children}:{unread:number;children:React.ReactNode}) {
  const scope=usePageReadScope(),owner=session.access_fingerprint;
  const notices:Inbox={items:[{id:'notice-A',kind:'outbid',required:true,revision:1,
    read_at:unread?null:'2030-01-02T00:00:00Z',cleared_at:null,event_time:'2030-01-01T00:00:00Z',resource_id:id,
    resource_revision:1,sample:true,destination:'/buyer'}],unread_count:unread,total_count:1,next_cursor:null};
  scope.client.setQueryData(optionsFor(scope,inboxRead(owner,null)).queryKey,notices);
  scope.client.setQueryData(optionsFor(scope,activityRead(owner,'leading',null)).queryKey,
    {schema_version:2,state:'available',total:0,next_cursor:null,items:[]});
  return children;
}
describe('Buyer-area presentation contract',()=>{
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
    const draftSubject='00000000-0000-4000-8000-000000000007';
    client.setQueryData<Readiness>(['l07','visual-owner','readiness',{reservation:'',quote:''}],{
      release:{payment:false,send_offer:false,accept_offer:false},reservation:{status:'not_selected'},
      quote:{status:'not_selected'},routes:[],drafts:[{id:'draft-A',subject_id:draftSubject,subject_revision:1,
        currency:'USD',amount_minor:50000,revision:1,updated_at:'2030-01-01T00:00:00Z',status:'draft'}],
    });
    const html=render(<BuyingPage/>);
    expect(html).toContain('pg-list-item');expect(html).toContain('ui-select');
    expect(html).toContain(draftSubject);expect(html).toContain(buyingCopy.draft);
    expect(button(html,buyingCopy.edit)).not.toContain('disabled=""');
    expect(button(html,buyingCopy.sendOffer)).toContain('disabled=""');
    expect(button(html,buyingCopy.pay)).toContain('disabled=""');
  });
  it.each(['en','ar'] as const)('renders the shared switch, unread status and independent notice actions in %s',locale=>{
    const copy=locale==='ar'?inboxAr:inboxEn;
    const html=render(<PageReadProvider><InboxFixture notices={{items:[{id:'notice-A',kind:'outbid',required:true,
      revision:1,read_at:null,cleared_at:null,event_time:'2030-01-01T00:00:00Z',resource_id:id,
      resource_revision:1,sample:true,destination:'/buyer'}],unread_count:1,total_count:1,next_cursor:null}}/></PageReadProvider>,locale);
    const switches=(html.match(/<input\b[^>]*>/g)??[]).filter(input=>/\srole="switch"/.test(input));
    expect(switches).toHaveLength(1);
    const [noticeSwitch]=switches;
    // The native checkbox supplies the switch's checked and enabled semantics.
    expect(noticeSwitch).toMatch(/\stype="checkbox"/);
    expect(noticeSwitch).toMatch(/\schecked=""/);
    expect(noticeSwitch).not.toMatch(/\sdisabled(?:=|\s|\/?>)|\saria-disabled="true"|\saria-checked="false"/);
    expect(html).toContain('role="listitem"');expect(html).toContain(copy.outbid);
    expect(html).toContain(`>${copy.unread}<`);
    for(const label of [copy.markRead,copy.clearNotice,copy.openRecord]) {
      expect(button(html,label)).not.toContain('disabled=""');
    }
  });
  it.each(['en','ar'] as const)('mounts buyer navigation and watch selection inside the declared workspace in %s',locale=>{
    settled.answer=true;
    const html=render(<PageReadProvider><WorkspaceFixture unread={1}><BuyerWorkspace/></WorkspaceFixture></PageReadProvider>,locale);
    expect(html).toContain('name="watch_id"');expect(html).toContain(`href="/${locale}/inbox"`);
    expect(html).toContain('●');expect(html).toContain(locale==='ar'?'إشعارات غير مقروءة':'Unread notices');
    expect(html).toContain(`action="/${locale}/checkout"`);expect(html).toContain('name="watch"');
    for(const entry of contracts) {
      expect(entry.proof).toBe('owed');expect(entry.kind).toBe('reads');
    }
  });
  it('removes the unread dot when no notices remain unread',()=>{
    settled.answer=true;
    expect(render(<PageReadProvider><WorkspaceFixture unread={0}><BuyerActions fingerprint="visual-owner"/></WorkspaceFixture></PageReadProvider>)).not.toContain('●');
  });
  it('resolves the selected watch to its listing and keeps real order links in the shared checkout list',()=>{
    const owner=session.access_fingerprint,listingId='00000000-0000-4000-8000-000000000008';
    const watch:Availability={watch_id:order.watch_id,listing_id:listingId,revision:3,status:'available',sale_mode:'fixed'};
    client.setQueryData(['l08-orders',owner],{items:[order]});
    client.setQueryData(['l13-checkout-watch',owner,watch.watch_id],watch);
    client.setQueryData(['l13-context',owner,listingId],{watch,listing:{id:listingId,revision:2,
      physical_watch_id:watch.watch_id,is_demo:true,facts:{brand:'Test Brand',model:'Selected Model',currency:'USD',price_minor:500000}}});
    const html=render(<Checkout watchId={watch.watch_id}/>);
    expect(html).toContain('hx-head');expect(html).toContain('ui-card');expect(html).toContain('pg-list-item');
    expect(html).toContain(`href="/en/checkout/${id}"`);
    expect(html).toContain('Test Brand Selected Model');expect(html).not.toContain('name="watch_id"');
    expect(button(html,connectedCopy.en.review)).not.toContain('disabled=""');
  });
  it('retains permission-gated hold and intake forms with the shared textarea',()=>{
    client.setQueryData(['l08-order','visual-owner',id,null],{order,history:[{action:'reserve',revision:1,occurred_at:'2030-01-01T00:00:00Z'}]});
    const html=render(<OrderDetail id={id}/>);
    expect(html).toContain('name="reason"');expect(html).toContain('name="actual_watch"');
    expect(html).toContain('ui-textarea');expect(html).toContain('pg-list-item');
    expect(html).toContain('<bdi dir="ltr">');
  });
});
