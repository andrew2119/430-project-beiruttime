import en from './en.json';
import ar from './ar.json';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import type {ReactElement} from 'react';
import BuyerPage from '@/app/(buyer)/buyer/page';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {LocaleContext} from '@/shell/locale-context';
import BuyerWorkspace from './buyer-workspace';
import {ApiError} from '@/lib/api/client';
import {activityRead} from './activity-read';
import {reservationsRead} from './buyer-reservations';
import {authenticatedRequest} from './session';
// Server rendering cannot run the mounted authorization refresh. These
// presentation cases supply its settled answer through the shared observer.
vi.mock('@/lib/page-speed/read',async load=>{
  const shared=await load<typeof import('@/lib/page-speed/read')>();
  return {...shared,usePageRead:(...args:Parameters<typeof shared.usePageRead>)=>({
    ...shared.usePageRead(...args),isFetchedAfterMount:true,isFetching:false,
  })};
});
const scope=vi.hoisted(()=>({current:null as unknown}));
vi.mock('@/lib/page-speed/provider',()=>({usePageReadScope:()=>scope.current}));
const session=vi.hoisted(()=>({state:'authenticated' as 'restoring'|'unavailable'|'signed-out'|'authenticated',fingerprint:'owner-A' as string|null,subjectId:'buyer-a',signedIn:true,organizationId:null as string|null,roles:['buyer']}));
vi.mock('./session',()=>({useBuyerSession:()=>session,authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
const activity={schema_version:2,state:'available',total:1000,next_cursor:'page-2',items:[{auction_id:'auction-A',listing_id:'watch-A',status:'leading',lifecycle:'live',current_price_minor:16000,currency:'USD',revision:1,starts_at:'2030-01-01T10:00:00Z',ends_at:'2030-01-01T12:00:00Z',private_maximum_minor:450000}]};
function render(data:unknown=activity,locale:'en'|'ar'='en',error?:ApiError,reservations?:unknown,resultView?:'won'|'calendar'|'released') {
  return renderBuyer(<BuyerWorkspace resultView={resultView}/>,data,locale,error,reservations,resultView);
}
function renderBuyer(page:ReactElement,data:unknown,locale:'en'|'ar',error?:ApiError,reservations?:unknown,resultView?:'won'|'calendar'|'released') {
  const client=new QueryClient();
  scope.current={key:'member:owner-A',client,valid:()=>true,claimArrival:()=>false};
  const key=['bt-page','member:owner-A',...activityRead('owner-A',resultView??'leading',null).key];
  client.setQueryData(key,data);
  if(reservations) client.setQueryData(['bt-page','member:owner-A',...reservationsRead('owner-A').key],reservations);
  if(error) client.getQueryCache().find({queryKey:key})!.setState({status:'error',error,fetchStatus:'idle'});
  return renderToStaticMarkup(<LocaleContext value={locale}><QueryClientProvider client={client}>{page}</QueryClientProvider></LocaleContext>);
}
beforeEach(()=>{session.state='authenticated';session.fingerprint='owner-A';session.signedIn=true;session.organizationId=null;session.roles=['buyer'];});
describe('current buyer activity',()=>{
  it.each(['restoring','unavailable','signed-out'] as const)('clears private presentation while identity is %s',state=>{
    session.state=state;
    const html=render();expect(html).not.toContain('auction-A');expect(html).not.toContain('name="watch_id"');
  });
  it('denies represented business scope and changed identity',()=>{
    session.organizationId='business';expect(render()).not.toContain('auction-A');
    session.organizationId=null;session.fingerprint='owner-B';expect(render()).not.toContain('auction-A');
  });
  it.each(['en','ar'] as const)('renders current facts, canonical controls and paging in %s',locale=>{
    const html=render(activity,locale);
    expect(html).toContain(locale==='en'?'My buying workspace':'مساحة المشتري');
    expect(html).toContain(locale==='en'?'Activity view':'عرض النشاط');
    expect(html).toContain(locale==='en'?'You are leading':'أنت المتصدر');
    expect(html).toContain('/'+locale+'/buyer/auctions/watch-A?auction=auction-A');
    expect(html).not.toContain('450000');expect(html).not.toContain('private_maximum_minor');
    expect(html).toContain(locale==='en'?'Next page':'الصفحة التالية');
    expect(html).toContain(locale==='ar'?'١٬٠٠٠':'1,000');
  });
  it.each([0,1,1000000])('uses the source total %s rather than visible row count',total=>{
    const html=render({...activity,total,items:[]});expect(html).toContain(new Intl.NumberFormat('en').format(total));
  });
  it('clears cached rows and totals after current access denial',()=>{
    const html=render({...activity,total:987654},'en',new ApiError(403,'denied',''));
    expect(html).not.toContain('987,654');expect(html).not.toContain('auction-A');
    expect(html).toContain('Your current account cannot use buyer actions.');
  });
  it('renders source outage and an actionable empty state',()=>{
    expect(render({schema_version:2,state:'unavailable',items:[],total:null,next_cursor:null})).toContain('Temporarily unavailable');
    expect(render({...activity,items:[],total:0,next_cursor:null})).toContain('No activity in this view');
  });
});


it.each(['en','ar'] as const)('uses the canonical listing reference for a result in %s',locale=>{
  const html=render({...activity,items:[{is_demo:true,auction_id:'auction-ended',watch_id:'physical-watch',listing_id:'catalog-listing',revision:2,state:'lost',currency:'USD',final_minor:500000,ended_at:'2030-01-01T00:00:00Z',order_id:null,financial_state:null,completed_sale:true,next_action:'view_auction'}]},locale);
  expect(html).toContain('/'+locale+'/buyer/auctions/catalog-listing?auction=auction-ended');
  expect(html).not.toContain('/watches/physical-watch');
  expect(html).toContain(locale==='ar'?'بيع مكتمل ومحرر':'Released completed sale');
  expect(html).not.toContain('/checkout/');
  expect(html).not.toContain('view=history');
});

it.each(['en','ar'] as const)('blocks changing views while current access is denied in %s',locale=>{
  const html=render(activity,locale,new ApiError(403,'denied',''));
  expect(html).toContain(locale==='ar'?'عرض النشاط':'Activity view');
  expect(html).toMatch(/role="radiogroup"[^>]*aria-disabled="true"/);
  expect(html).not.toContain('name="watch_id"');
});

it.each(['en','ar'] as const)('shows a stale cursor recovery without outdated rows in %s',locale=>{
  const html=render(activity,locale,new ApiError(409,'stale_cursor',''));
  expect(html).toContain(locale==='ar'?'تغيّر النشاط':'Activity has changed');
  expect(html).toContain(locale==='ar'?'العودة إلى الصفحة الأولى':'Return to first page');
  expect(html).not.toContain('auction-A');
});

it.each(['en','ar'] as const)('renders a validated mixed-language listing title and handles missing source facts in %s',async locale=>{
  const title='مرجع الساعة Auction العربية ⌚✨ '.repeat(7).trim();
  const bid={auction_id:'00000000-0000-4000-8000-000000000001',
    listing_id:'00000000-0000-4000-8000-000000000002',status:'leading',lifecycle:'live',
    current_price_minor:16000,currency:'USD',revision:1,is_demo:true,
    starts_at:'2030-01-01T10:00:00Z',ends_at:'2030-01-01T12:00:00Z'};
  const page={schema_version:2,state:'available',items:[{...bid,listing_title:title}],total:1,next_cursor:null};
  const ask=()=>activityRead('owner-A','leading',null).ask(new AbortController().signal);
  vi.mocked(authenticatedRequest).mockResolvedValueOnce(page);
  expect(render(await ask(),locale)).toContain('<bdi>'+title+'</bdi>');

  vi.mocked(authenticatedRequest).mockResolvedValueOnce({...page,items:[bid]});
  expect(render(await ask(),locale)).toContain(bid.auction_id);

  for(const change of [{ends_at:undefined},{auction_id:title},{listing_title:'⌚'.repeat(241)}]) {
    vi.mocked(authenticatedRequest).mockResolvedValueOnce({...page,items:[{...bid,...change}]});
    const error=await ask().catch((failure:unknown)=>failure);
    expect(error).toMatchObject({status:503,code:'invalid_activity_page'});
    const html=render(page,locale,error as ApiError);
    expect(html).toContain(locale==='en'?'Temporarily unavailable':'الخدمة غير متاحة مؤقتاً');
    expect(html).not.toContain(title);
    expect(html).not.toContain(bid.auction_id);
  }
});

it.each([
  ['pending','review_order','Payment is pending','الدفع قيد الانتظار'],
  ['unknown','contact_support','Payment status is uncertain','حالة الدفع غير مؤكدة'],
  ['paid_held','review_order','Payment is confirmed and held','تأكد الدفع والمبلغ محتجز'],
] as const)('shows %s payment and its next action in both languages',(financial_state,next_action,en,ar)=>{
  for(const locale of ['en','ar'] as const) {
    const html=render({...activity,items:[{is_demo:true,auction_id:'auction-ended',watch_id:'physical-watch',
      listing_id:'catalog-listing',revision:2,state:'won',currency:'USD',final_minor:500000,
      ended_at:'2030-01-01T00:00:00Z',order_id:'order-test',financial_state,completed_sale:false,next_action}]},locale);
    expect(html).toContain(locale==='en'?en:ar);
    expect(html).toContain(locale==='en'?'Won':'فزت');
    if(next_action==='review_order') expect(html).toContain('/'+locale+'/checkout/order-test');
    else {
      expect(html).toContain(`href="/${locale}/buyer/auctions/catalog-listing/support?auction=auction-ended"`);
      expect(html).toContain('/'+locale+'/checkout/order-test');
    }
  }
});

it.each(['en','ar'] as const)('keeps reservation details available during an activity outage in %s',locale=>{
  const reservations={state:'available',next_cursor:null,items:[{
    reservation_id:'test-reservation',state:'awaiting_payment',total_minor:24000,
    currency:'USD',expires_at:'2030-01-01T12:00:00Z',is_demo:true,
  }]};
  const html=render({schema_version:2,state:'unavailable',items:[],total:null,next_cursor:null},locale,undefined,reservations);
  expect(html).toContain(locale==='en'?'Temporarily unavailable':'الخدمة غير متاحة مؤقتاً');
  expect(html).not.toContain('auction-A');
  expect(html).toContain(`href="/${locale}/inbox"`);
  expect(html).toContain('name="watch_id"');
  expect(html).toContain(locale==='en'?'Awaiting payment':'بانتظار الدفع');
  expect(html).toContain(locale==='en'?'240.00 USD':'٢٤٠٫٠٠ USD');
  const expiry=new Intl.DateTimeFormat(locale==='ar'?'ar-LB':'en-LB',{
    dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut',numberingSystem:locale==='ar'?'arab':'latn',
  }).format(new Date('2030-01-01T12:00:00Z'));
  expect(html).toContain(expiry);
  expect(html).toContain(`/${locale}/checkout/test-reservation`);
});

it('keeps activity available when reservations are unavailable',()=>{
  const html=render(activity,'en',undefined,{state:'unavailable',items:[],next_cursor:null});
  expect(html).toContain('You are leading');
  expect(html).toContain('Temporarily unavailable');
  expect(html).not.toContain('No reservations yet');
});

vi.mock('@/shell/foundation/path',async importOriginal=>({
  ...await importOriginal<typeof import('@/shell/foundation/path')>(),usesFoundationShell:()=>true,
}));

vi.mock('next/navigation',()=>({useRouter:()=>({refresh:vi.fn()}),usePathname:()=>'/en/buyer'}));

it.each([503,403])('hides buyer data and actions when current identity fails with %s',status=>{
  const reservations={state:'available',next_cursor:null,items:[{reservation_id:'test-private-reservation'}]};
  const html=render(activity,'en',new ApiError(status,status===503?'unavailable':'denied','test-read'),reservations);
  expect(html).not.toContain('auction-A');
  expect(html).not.toContain('test-private-reservation');
  expect(html).not.toContain('name="watch_id"');
  expect(html).not.toContain('href="/en/inbox"');
});

it.each(['en','ar'] as const)('routes held wins and uncertain payments to their own conversation in %s',async locale=>{
  const t=locale==='ar'?ar:en;
  for(const order of [null,'order-held']) {
    const data={schema_version:2,state:'available',total:1,next_cursor:null,items:[{
      auction_id:'auction-held',listing_id:'listing-held',state:'won',final_minor:500000,
      ended_at:'2030-01-01T00:00:00Z',order_id:order,financial_state:order?'unknown':'pending',
      completed_sale:false,next_action:'contact_support',
    }]};
    const page=await BuyerPage({searchParams:Promise.resolve({view:'won'})});
    const html=renderBuyer(page,data,locale,undefined,undefined,'won');
    expect(html).toContain(`href="/${locale}/buyer/auctions/listing-held/support?auction=auction-held"`);
    expect(html).toContain(t.contactSupport);
    expect(html).toContain(order?t.checkResult:t.checkAllocation);
    expect(html).not.toContain('mailto:');
    const denied=renderBuyer(page,data,locale,new ApiError(403,'denied',''),undefined,'won');
    expect(denied).not.toContain(t.contactSupport);
    expect(denied).not.toContain('auction-held');
  }
});

it.each(['en','ar'] as const)('finds the same auction support history from Won and Released after payment resolves in %s',locale=>{
  const t=locale==='ar'?ar:en;
  const auction='00000000-0000-4000-8000-000000000015',listing='00000000-0000-4000-8000-000000000016';
  const result={auction_id:auction,listing_id:listing,state:'won',final_minor:500000,
    ended_at:'2030-01-01T00:00:00Z',order_id:'order-current',completed_sale:false};
  const page=(item:unknown)=>({...activity,items:[item],total:1,next_cursor:null});
  const contact=`/${locale}/buyer/auctions/${listing}/support?auction=${auction}`;
  const held=render(page({...result,financial_state:'unknown',next_action:'contact_support'}),locale,undefined,undefined,'won');
  expect(held).toContain(`${contact}"`);
  expect(held).toContain(t.contactSupport);
  for(const view of ['won','released'] as const) {
    const resolved=render(page({...result,financial_state:'released',completed_sale:true,next_action:'review_order'}),locale,undefined,undefined,view);
    expect(resolved).toContain(`${contact}&amp;view=history"`);
    expect(resolved).toContain(t.checkSupportHistory);
    expect(resolved).not.toContain(t.contactSupport);
    expect(resolved).toContain(`/${locale}/checkout/order-current`);
  }
});

it.each(['en','ar'] as const)('opens the Won view and exposes the current order action in %s',locale=>{
  const page={...activity,items:[{auction_id:'auction-closed',state:'won',final_minor:500000,
    ended_at:'2030-01-01T00:00:00Z',order_id:'order-current',financial_state:'unpaid',
    completed_sale:false,next_action:'review_order'}]};
  const html=render(page,locale,undefined,undefined,'won');
  expect(html).toContain(`/${locale}/checkout/order-current`);
  expect(html).toContain(locale==='ar'?'الدفع مستحق':'Payment is due');
});

it.each(['en','ar'] as const)('shows an unavailable producer, not an empty or paged list, in %s',locale=>{
  const html=render({schema_version:2,state:'unavailable',items:[],total:null,next_cursor:null},locale);
  expect(html).toContain(locale==='en'?'Temporarily unavailable':'الخدمة غير متاحة مؤقتاً');
  expect(html).not.toContain(locale==='en'?'No activity in this view':'لا يوجد نشاط في هذا العرض');
  expect(html).not.toContain(locale==='en'?'Next page':'الصفحة التالية');
});

it('hides auction activity while allowing independently authorized reservations',()=>{
  const reservations={state:'available',next_cursor:null,items:[{
    reservation_id:'test-reservation',state:'awaiting_payment',total_minor:24000,
    currency:'USD',expires_at:'2030-01-01T12:00:00Z',is_demo:true,
  }]};
  const html=render(activity,'en',new ApiError(403,'auction_access_denied','test-read'),reservations);
  expect(html).not.toContain('auction-A');
  expect(html).not.toContain('1,000');
  expect(html).toContain('/en/checkout/test-reservation');
});

it.each(['en','ar'] as const)('represents zero-price calendar snapshots as no bids in %s',async locale=>{
  for(const lifecycle of ['scheduled','live'] as const) {
    const item={
      auction_id:'00000000-0000-4000-8000-000000000001',
      listing_id:'00000000-0000-4000-8000-000000000002',
      revision:1,currency:'USD',is_demo:true,status:null,lifecycle,current_price_minor:0,
      starts_at:'2030-01-01T10:00:00Z',ends_at:'2030-01-01T12:00:00Z',
    };
    vi.mocked(authenticatedRequest).mockResolvedValueOnce({
      schema_version:2,state:'available',total:1,next_cursor:null,items:[item],
    });
    const page=await activityRead('owner-A','calendar',null).ask(new AbortController().signal);
    const html=render(page,locale,undefined,undefined,'calendar');
    expect(html).toContain(locale==='en'?'No accepted bids':'لا مزايدات مقبولة');
    expect(html).not.toContain(locale==='en'?'0.00 USD':'٠٫٠٠ USD');
  }
});

it.each(['en','ar'] as const)('keeps legacy currency reservation data outside the active checkout view in %s',locale=>{
  const usd={reservation_id:'test-current-reservation',state:'awaiting_payment',total_minor:24000,
    currency:'USD',expires_at:'2030-01-01T12:00:00Z',is_demo:true};
  const legacy={...usd,reservation_id:'test-archived-reservation',currency:'LBP',total_minor:123456};
  const html=render(activity,locale,undefined,{state:'available',next_cursor:null,items:[legacy,usd]});
  expect(html).toContain(`/${locale}/checkout/${usd.reservation_id}`);
  expect(html).not.toContain(legacy.reservation_id);
});
