import {beforeEach,describe,it,expect,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {LocaleContext} from '@/shell/locale-context';
import {BuyerAuctionView,MaximumForm} from './proxy-bid';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
const source=vi.hoisted(()=>({current:{} as Record<string,unknown>}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>source.current}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:React.ReactNode})=>children}));
const session=vi.hoisted(()=>({state:'authenticated' as 'restoring'|'unavailable'|'signed-out'|'authenticated',signedIn:true,organizationId:null as string|null,fingerprint:'buyer-A',subjectId:'00000000-0000-0000-0000-000000000001',roles:['buyer']}));
vi.mock('./session',()=>({useBuyerSession:()=>session,authenticatedRequest:vi.fn(),refreshSession:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
beforeEach(()=>{session.state='authenticated';session.signedIn=true;session.organizationId=null;session.roles=['buyer'];});
const lot:AuctionSnapshot&{mode:'bidding'}={mode:'bidding',id:'00000000-0000-0000-0000-000000000006',listing_id:'00000000-0000-0000-0000-000000000007',currency:'USD',opening_minor:400000,current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',server_time:'2030-01-01T12:00:00Z',revision:4,accepted_sequence:1,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:'Bidder 1a2b3c4d',status:'live'};
function slot(data:unknown) {
  source.current={data,isSuccess:true,refetch:vi.fn()};
  return renderToStaticMarkup(<BuyerAuctionView locale="en" listingId={lot.listing_id}/>);
}
describe('canonical buyer auction page',()=>{
  it('renders the maximum control for a canonical live lot',()=>{
    const html=slot({items:[lot]});expect(html).toContain('Review maximum and fees');expect(html).toContain('Your maximum (USD)');
  });
  it.each([
    ['scheduled','2029-12-31T23:59:59+00:00','Bidding has not opened'],
    ['live','2030-01-01T00:00:00+00:00','Review maximum and fees'],
    ['live','2030-01-01T23:59:59+00:00','Review maximum and fees'],
    ['ended','2030-01-02T00:00:00+00:00','This auction has ended'],
    ['ended','2030-01-02T00:00:01+00:00','This auction has ended'],
  ] as const)('keeps a no-bid %s auction visible at %s', (status,server_time,message)=>{
    const html=slot({items:[{...lot,status,server_time,
      starts_at:'2030-01-01T00:00:00+00:00',ends_at:'2030-01-02T00:00:00+00:00',
      current_minor:0,opening_minor:400000,next_minimum_minor:400000,accepted_sequence:0,leader:null,
    }]});
    expect(html).toContain('Opening price');
    expect(html).toContain('4,000.00 USD');
    expect(html).toContain(message);
    if(status!=='live') expect(html).not.toContain('Review maximum and fees');
  });
  it.each(['scheduled','ended'] as const)('does not permit bids on %s auctions',status=>{
    const html=slot({items:[{...lot,status,server_time:status==='scheduled'?'2019-01-01T00:00:00Z':lot.ends_at}]});expect(html).not.toContain('Your maximum (USD)');
    expect(html).toContain(status==='ended'?'This auction has ended':'Bidding has not opened');
    expect(html).not.toContain('You won');
  });
  it.each([{id:'not-an-auction'},{listing_id:'another-listing'},{revision:0},{revision:1.5},{currency:'EUR'}])('does not offer a quote for malformed or mismatched canonical identity %j',change=>{
    const html=slot({items:[{...lot,...change}]});expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('Your maximum (USD)');
  });
  it.each([
    {opening_minor:undefined}, {opening_minor:410000},
    {leader:undefined}, {leader:null}, {leader:'unmasked-private-id'},
    {current_minor:undefined}, {current_minor:NaN}, {current_minor:0}, {next_minimum_minor:undefined},
    {high_value_minor:undefined}, {high_value_minor:0}, {server_time:undefined},
    {server_time:lot.ends_at}, {starts_at:'invalid'}, {ends_at:lot.starts_at},
  ])('withholds bidding for incomplete or invalid public facts %j', change=>{
    const html=slot({items:[{...lot,...change}]});
    expect(html).toContain('Temporarily unavailable');
    expect(html).not.toContain('Review maximum and fees');
    expect(html).not.toContain('NaN');
  });
  it('does not turn a malformed public page into empty-success bidding',()=>{
    const html=slot({unexpected:[]});expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('Your maximum (USD)');
  });
});
describe('maximum form capability boundary',()=>{
  it.each(['restoring','unavailable'] as const)('cannot submit while the current identity is %s',state=>{
    session.state=state;
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).not.toContain('<input');expect(html).not.toContain('type="submit"');
    expect(html).toContain(state==='restoring'?'Loading':'Temporarily unavailable');
  });
  it('requires individual context even if a represented session has the buyer role',()=>{
    session.organizationId='business-A';
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Your current account cannot use buyer actions.');expect(html).not.toContain('<input');
  });
  it('renders permission denial rather than a fabricated buyer or submit control',()=>{
    session.roles=['operator'];
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Your current account cannot use buyer actions.');expect(html).not.toContain('<input');
  });
  it('preserves the non-secret intended auction route when signing in',()=>{
    session.state='signed-out';session.signedIn=false;
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} signInNext="/buyer/auctions/watch-A" getQuote={vi.fn()}/>);
    expect(html).toContain('/en/account?next=%2Fbuyer%2Fauctions%2Fwatch-A');expect(html).not.toContain('<input');
  });
  it('never enables submission without the current bound pricing capability',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}}/>);
    expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('Your maximum (USD)');expect(html).not.toContain('Review maximum and fees');
  });
  it('requires review before confirmation and keeps secret inputs unpersisted',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Review maximum and fees');expect(html).toContain('inputMode="decimal"');
    expect(html).toContain('autoComplete="off"');expect(html).not.toContain('buyer-A');
    expect(html).not.toContain('Set private maximum');

  });
  it('uses Arabic copy and isolated currency without a second form implementation',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="ar" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('مراجعة الحد الأقصى والرسوم');expect(html).toContain('(USD)');
  });
});

it.each(['en','ar'] as const)('discloses the verified-contact threshold before confirmation in %s',locale=>{
  const html=renderToStaticMarkup(<MaximumForm auctionId={lot.id} revision={lot.revision}
    currency="USD" locale={locale} highValueMinor={lot.high_value_minor} onRefresh={()=>{}} getQuote={vi.fn()}/>);
  const explanation=locale==='en'?'A verified contact is required for bids at or above':'يلزم توثيق وسيلة اتصال للمزايدات التي تساوي أو تتجاوز';
  expect(html).toContain(explanation);
  expect(html).toContain(locale==='en'?'10,000.00 USD':'١٠٬٠٠٠٫٠٠ USD');
});

vi.mock('@/shell/foundation/path',async importOriginal=>({
  ...await importOriginal<typeof import('@/shell/foundation/path')>(),usesFoundationShell:()=>true,
}));

it('keeps a selected prior auction separate from a replacement on the same listing',()=>{
  const prior={...lot,status:'ended' as const,server_time:lot.ends_at};
  const replacement={...lot,id:'00000000-0000-0000-0000-000000000008'};
  function render(data:AuctionSnapshot) {
    source.current={data:{items:[data]},isSuccess:true,refetch:vi.fn()};
    return renderToStaticMarkup(<BuyerAuctionView locale="en" listingId={lot.listing_id} auctionId={prior.id}/>);
  }
  const original=render(prior);
  expect(original).toContain('This auction has ended');
  expect(original).not.toContain('Review maximum and fees');
  const wrong=render(replacement);
  expect(wrong).toContain('Temporarily unavailable');
  expect(wrong).not.toContain('Current price');
  expect(wrong).not.toContain('Review maximum and fees');
});

vi.mock('next/navigation',()=>({useRouter:()=>({refresh:vi.fn()}),usePathname:()=>'/en/buyer'}));

it.each(['first_bid_pending','listing_edit_pending','prebid_pending',undefined] as const)(
  'withholds fresh bidding for the selected auction in mode %s without hiding public facts',mode=>{
    source.current={data:{items:[{...lot,mode}]},isSuccess:true,refetch:vi.fn()};
    const html=renderToStaticMarkup(<BuyerAuctionView locale="en" listingId={lot.listing_id} auctionId={lot.id}/>);
    expect(html).toContain('Masked accepted history');
    expect(html).toContain(mode?'Bidding is on hold':'Temporarily unavailable');
    expect(html).not.toContain('Review maximum and fees');
  },
);


it.each(['live', 'ended'] as const)('preserves the %s auction when the next bid exceeds the supported range', status=>{
  const html=slot({items:[{...lot,status,
    server_time:status==='ended'?lot.ends_at:lot.server_time,
    current_minor:9_000_000_000_000_000,next_minimum_minor:9_100_000_000_000_000,
    increment_bands:[{from_minor:0,step_minor:100_000_000_000_000}],
  }]});
  expect(html).toContain('90,000,000,000,000.00 USD');
  expect(html).toContain('No higher bid available');
  expect(html).toContain('Masked accepted history');
  expect(html).toContain(status==='ended'?'This auction has ended':'This auction has reached its bidding limit.');
  expect(html).not.toContain('Review maximum and fees');
});


it.each([
  ['2030-03-31T23:59:59.999Z', true],
  ['2030-04-01T00:00:00.000Z', true],
  ['2030-04-01T00:00:00.001Z', false],
] as const)('validates auction duration through %s before enabling a fresh bid', (ends_at, valid) => {
  const html = slot({items: [{...lot, ends_at}]});
  expect(html).toContain(valid ? 'Review maximum and fees' : 'Temporarily unavailable');
  if (!valid) expect(html).not.toContain('Review maximum and fees');
});


it.each(['en','ar'] as const)('links a confirmed ended auction to current results in %s',locale=>{
  source.current={data:{items:[{...lot,status:'ended',server_time:lot.ends_at}]},isSuccess:true,refetch:vi.fn()};
  const html=renderToStaticMarkup(<LocaleContext value={locale}>
    <BuyerAuctionView locale={locale} listingId={lot.listing_id}/>
  </LocaleContext>);
  expect(html).toContain(locale==='ar'?'انتهى هذا المزاد.':'This auction has ended.');
  expect(html).toContain(`href="/${locale}/buyer?view=won"`);
  expect(html).toContain(locale==='ar'?'عرض نتائج مزاداتي':'View my auction results');
  expect(html).not.toContain(locale==='ar'?'النتائج النهائية والدفع غير متاحين':'Final results and payment are not available');
});


it.each([
  {next_minimum_minor:430000},
  {next_minimum_minor:439999},
  {next_minimum_minor:440001},
  {increment_bands:[{from_minor:430000,step_minor:10000}]},
  {increment_bands:[{from_minor:0,step_minor:10000},{from_minor:430000,step_minor:20000}]},
])('retains the public record and receipt recovery with inconsistent bid rules %j', change=>{
  const html=slot({items:[{...lot,current_minor:430000,next_minimum_minor:440000,...change}]});
  expect(html).toContain('Current price');
  expect(html).toContain('4,300.00 USD');
  expect(html).toContain('Masked accepted history');
  expect(html).toContain('Temporarily unavailable');
  expect(html).not.toContain('Review maximum and fees');
});

it('uses the increment starting exactly at the current price',()=>{
  const html=slot({items:[{...lot,current_minor:430000,next_minimum_minor:450000,
    increment_bands:[{from_minor:0,step_minor:10000},{from_minor:430000,step_minor:20000}]}]});
  expect(html).toContain('4,500.00 USD');
  expect(html).toContain('Review maximum and fees');
});

it.each([
  ['2029-12-31T23:59:59.999999Z','scheduled','Bidding has not opened','1 second'],
  ['2030-01-01T00:00:00.000000Z','live','Review maximum and fees','86,400 seconds'],
  ['2030-01-01T00:00:00.000001Z','live','Review maximum and fees','86,400 seconds'],
  ['2030-01-01T23:59:59.999999Z','live','Review maximum and fees','1 second'],
  ['2030-01-02T00:00:00.000000Z','ended','This auction has ended','0 seconds'],
  ['2030-01-02T00:00:00.000001Z','ended','This auction has ended','0 seconds'],
] as const)('renders authoritative auction timing at %s', (server_time,status,message,countdown)=>{
  const html=slot({items:[{...lot,server_time,status,current_minor:0,leader:null,accepted_sequence:0,
    next_minimum_minor:lot.opening_minor}]});
  expect(html).toContain(message);
  expect(html).toContain(countdown);
});

it.each([['en','Fee preview limit reached'],['ar','تم بلوغ حد معاينة الرسوم']] as const)(
  'preserves the public record when every opening maximum exceeds the preview limit in %s',(locale,message)=>{
    const opening_minor=9_000_000_000_001;
    source.current={data:{items:[{...lot,opening_minor,current_minor:0,next_minimum_minor:opening_minor,
      accepted_sequence:0,leader:null}]},isSuccess:true,refetch:vi.fn()};
    const html=renderToStaticMarkup(<LocaleContext value={locale}>
      <BuyerAuctionView locale={locale} listingId={lot.listing_id}/>
    </LocaleContext>);
    expect(html).toContain(message);
    expect(html).toContain(locale==='en'?'Opening price':'سعر الافتتاح');
    expect(html).toContain(locale==='en'?'Masked accepted history':'سجل المزايدات المقبولة بهويات محجوبة');
    expect(html).not.toContain(locale==='en'?'Review maximum and fees':'مراجعة الحد الأقصى والرسوم');
  },
);

it('allows an opening maximum exactly at the preview limit',()=>{
  const opening_minor=9_000_000_000_000;
  const html=slot({items:[{...lot,opening_minor,current_minor:0,next_minimum_minor:opening_minor,
    accepted_sequence:0,leader:null}]});
  expect(html).toContain('Review maximum and fees');
});
