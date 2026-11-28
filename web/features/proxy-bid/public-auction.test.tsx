import {expect,it,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {LocaleContext} from '@/shell/locale-context';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
import {BuyerAuctionView,PublicAuctionFacts} from './proxy-bid';
const source=vi.hoisted(()=>({current:{} as Record<string,unknown>}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>source.current}));
const auction={id:'auction-test',revision:3,accepted_sequence:2,leader:'Bidder 1a2b3c4d',status:'live',current_minor:430000,next_minimum_minor:440000,starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',server_time:'2030-01-01T23:59:59Z'} as AuctionSnapshot;
it.each(['en','ar'] as const)('shows public facts and masked accepted history in %s',locale=>{
  source.current={data:{snapshot:auction,items:[{sequence:1,bidder:'Bidder 1a2b3c4d',amount_minor:420000}],has_more:true,next_sequence:1}};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale={locale}/>);
  expect(html).toContain(locale==='en'?'Next minimum':'الحد الأدنى التالي');
  expect(html).toContain(locale==='ar'?'مزايد':'Bidder');
  expect(html).toContain('1a2b3c4d');
  if(locale==='ar') expect(html).not.toContain('Bidder');
  expect(html).toContain(locale==='en'?'More accepted bids':'المزيد من المزايدات المقبولة');
});
it.each([['2030-01-01T23:59:59Z','1 second'],['2030-01-02T00:00:00Z','0 seconds'],['2030-01-02T00:00:01Z','0 seconds']])('counts down from authoritative time %s',(server_time,text)=>{
  source.current={isPending:true};
  expect(renderToStaticMarkup(<PublicAuctionFacts auction={{...auction,server_time}} locale="en"/>)).toContain(`>${text}</dd>`);
});
it('keeps the final public bid visible after a private ceiling raise',()=>{
  source.current={data:{snapshot:auction,items:[{sequence:1,bidder:'Bidder 1a2b3c4d',amount_minor:430000}],
    has_more:false,next_sequence:1}};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale="en"/>);
  expect(html).toContain('1a2b3c4d');
  expect(html).toContain('4,300.00 USD');
  expect(html).not.toContain('Bid history unavailable');
  expect(html).not.toContain('More accepted bids');
});
it('shows unavailable history with retry rather than invented empty history',()=>{
  source.current={isError:true,refetch:vi.fn()};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale="en"/>);
  expect(html).toContain('Bid history unavailable');expect(html).not.toContain('No accepted bids');
});
it.each([
  {items:[]},
  {snapshot:null,items:[]},
  {snapshot:auction},
  {snapshot:auction,items:{}},
  {snapshot:auction,items:[null]},
  {snapshot:auction,items:[],has_more:true,next_sequence:0},
  {snapshot:auction,items:[],has_more:false,next_sequence:0},
  {snapshot:auction,items:[{sequence:1,bidder:'Bidder 1a2b3c4d',amount_minor:430000}],has_more:false,next_sequence:2},
  {snapshot:auction,items:[{sequence:3,bidder:'Bidder 1a2b3c4d',amount_minor:430000}],has_more:false,next_sequence:3},
])('shows retry for malformed history %j',data=>{
  source.current={data,isSuccess:true,refetch:vi.fn()};
  for(const locale of ['en','ar'] as const) {
    const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale={locale}/>);
    expect(html).toContain(locale==='en'?'Bid history unavailable':'سجل المزايدات غير متاح');
    expect(html).toContain(locale==='en'?'Try again':'حاول مجدداً');
    expect(html).not.toContain(locale==='en'?'No accepted bids':'لا مزايدات مقبولة');
  }
});
it.each([[2,1],[1,1]])('rejects non-increasing public sequences %j',(...sequences)=>{
  const items=sequences.map(sequence=>({sequence,bidder:'Bidder 1a2b3c4d',amount_minor:430000}));
  source.current={data:{snapshot:auction,items,has_more:false,next_sequence:sequences.at(-1)},refetch:vi.fn()};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale="en"/>);
  expect(html).toContain('Bid history unavailable');
  expect(html).toContain('Try again');
  expect(html).not.toContain('1a2b3c4d');
});

it('preserves increasing public sequences across private raises',()=>{
  const snapshot={...auction,accepted_sequence:4,current_minor:440000};
  const items=[1,3].map(sequence=>({sequence,bidder:'Bidder 1a2b3c4d',amount_minor:410000+sequence*10000}));
  source.current={data:{snapshot,items,has_more:false,next_sequence:3}};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={snapshot} locale="en"/>);
  expect(html).not.toContain('Bid history unavailable');
  expect(html).toContain('4,200.00 USD');
  expect(html).toContain('4,400.00 USD');
});

it('renders an actual empty history only from a matching result',()=>{
  const noBids={...auction,accepted_sequence:0};
  source.current={data:{snapshot:noBids,items:[],has_more:false,next_sequence:0}};
  expect(renderToStaticMarkup(<PublicAuctionFacts auction={noBids} locale="en"/>)).toContain('No accepted bids');
});

vi.mock('./session',()=>({useBuyerSession:()=>({state:'signed-out',signedIn:false,fingerprint:null,roles:[]})}));
it.each([['23:59:57','٣ ثوان'],['23:59:58','ثانيتان'],['23:59:59','ثانية'],['00:00:00','٠ ثانية']])('localizes Arabic countdown at %s',(clock,text)=>{
  source.current={isPending:true};
  expect(renderToStaticMarkup(<PublicAuctionFacts auction={{...auction,server_time:`2030-01-${clock==='00:00:00'?'02':'01'}T${clock}Z`}} locale="ar"/>)).toContain(`>${text}</dd>`);
});
it.each(['en','ar'] as const)('explains an empty buyer auction response with recovery in %s',locale=>{
  source.current={data:{items:[]},isSuccess:true,refetch:vi.fn()};
  const html=renderToStaticMarkup(<LocaleContext value={locale}><BuyerAuctionView locale="en" listingId="listing-test"/></LocaleContext>);
  expect(html).toContain(locale==='en'?'Temporarily unavailable':'الخدمة غير متاحة مؤقتاً');
  expect(html).toContain(locale==='en'?'Refresh to check current access':'حدّث للتحقق من الصلاحية');
  expect(html).toContain(locale==='en'?'Try again':'حاول مجدداً');
});

it.each(['buyer@example.invalid','Bidder 1a2b3c4d\n','Bidder 1A2B3C4D'])('withholds invalid history label %j',bidder=>{
  source.current={data:{snapshot:auction,items:[{sequence:2,bidder,amount_minor:430000}],has_more:false,next_sequence:2}};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale="en"/>);
  expect(html).toContain('Bid history unavailable');
  expect(html).not.toContain(bidder.trim());
});

vi.mock('@/shell/foundation/path',async importOriginal=>({
  ...await importOriginal<typeof import('@/shell/foundation/path')>(),usesFoundationShell:()=>true,
}));

vi.mock('next/navigation',()=>({useRouter:()=>({refresh:vi.fn()}),usePathname:()=>'/en/buyer'}));

it.each([
  {amount_minor:420000},
  {amount_minor:440000},
  {bidder:'Bidder 5e6f7890'},
])('rejects a final public bid inconsistent with the current price or leader %j',change=>{
  const final={sequence:1,bidder:auction.leader,amount_minor:auction.current_minor,...change};
  source.current={data:{snapshot:auction,items:[final],has_more:false,next_sequence:1}};
  const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale="en"/>);
  expect(html).toContain('Bid history unavailable');
  expect(html).toContain('Try again');
  expect(html).not.toContain(final.bidder?.slice(7));
});

it('withholds history when a previous public bid exceeds the final price',()=>{
  const items=[
    {sequence:1,bidder:'Bidder 5e6f7890',amount_minor:440000},
    {sequence:2,bidder:auction.leader,amount_minor:auction.current_minor},
  ];
  source.current={data:{snapshot:auction,items,has_more:false,next_sequence:2},refetch:vi.fn()};
  for(const locale of ['en','ar'] as const) {
    const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale={locale}/>);
    expect(html).toContain(locale==='en'?'Bid history unavailable':'سجل المزايدات غير متاح');
    expect(html).toContain(locale==='en'?'Try again':'حاول مجدداً');
    expect(html).not.toContain('5e6f7890');
  }
});

it.each([false,true])('preserves historical ties including at a page boundary (%s)',has_more=>{
  const first={sequence:1,bidder:'Bidder 5e6f7890',amount_minor:auction.current_minor,automatic:false};
  const final={sequence:2,bidder:auction.leader,amount_minor:auction.current_minor,automatic:true};
  source.current={data:{snapshot:auction,items:has_more?[first]:[first,final],has_more,next_sequence:has_more?1:2}};
  for(const locale of ['en','ar'] as const) {
    const html=renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale={locale}/>);
    expect(html).toContain('5e6f7890');
    expect(html).not.toContain(locale==='en'?'Bid history unavailable':'سجل المزايدات غير متاح');
    expect(html).toContain(has_more?(locale==='en'?'More accepted bids':'المزيد من المزايدات المقبولة'):'1a2b3c4d');
  }
});

it('rejects an equal manual bid in public history',()=>{
  const items=[
    {sequence:1,bidder:'Bidder 5e6f7890',amount_minor:auction.current_minor,automatic:false},
    {sequence:2,bidder:auction.leader,amount_minor:auction.current_minor,automatic:false},
  ];
  source.current={data:{snapshot:auction,items,has_more:false,next_sequence:2}};
  expect(renderToStaticMarkup(<PublicAuctionFacts auction={auction} locale="en"/>)).toContain('Bid history unavailable');
});
