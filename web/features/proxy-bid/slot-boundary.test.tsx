import {expect,it,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {auctionTiming,observeAuctionEnd} from './auction-time';

const source=vi.hoisted(()=>({read:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:source.read}));

const listing='00000000-0000-4000-8000-000000000001';
const auction={
  id:'00000000-0000-4000-8000-000000000002',
  listing_id:listing,currency:'USD',revision:1,status:'live',
  starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-02T00:00:00Z',server_time:'2030-01-01T23:59:59Z',
} as const;

it('opens the exact current auction from the registered watch shortcut',async()=>{
  const {default:registration}=await import('@/registrations/L06');
  const {default:Slot}=await registration.slots.find(slot=>slot.target==='watch.detail')!.load();
  const draw=(locale:'en'|'ar'='en')=>renderToStaticMarkup(<Slot locale={locale} resourceId={listing}/>);
  source.read.mockReturnValue({});
  expect(draw()).toBe('');
  expect(source.read.mock.calls[0][0].key).toEqual(['listing-auction',listing]);
  source.read.mockReturnValue({data:{items:[]}});
  expect(draw()).toBe('');
  source.read.mockReturnValue({data:{items:[auction]}});
  expect(draw()).toContain('Private maximum bid');
  expect(draw('ar')).toContain('الحد الأقصى الخاص للمزايدة');
  expect(draw()).toContain(`href="/en/buyer/auctions/${listing}?auction=${auction.id}"`);
  source.read.mockReturnValue({data:{items:[auction]},isError:true});
  expect(draw()).toBe('');
  source.read.mockReturnValue({data:{items:[{...auction,status:'ended',server_time:auction.ends_at}]}});
  expect(draw()).toBe('');
  source.read.mockReturnValue({data:{items:[{...auction,mode:'first_bid_pending'}]}});
  expect(draw()).toBe('');
  source.read.mockReturnValue({data:{items:[{...auction,listing_id:auction.id}]}});
  expect(draw()).toBe('');
  const replacement='00000000-0000-4000-8000-000000000003';
  source.read.mockReturnValue({data:{items:[{...auction,id:replacement}]}});
  expect(draw()).toContain(`?auction=${replacement}"`);
});

it('hides an elapsed server window without making another read',()=>{
  vi.useFakeTimers({toFake:['setTimeout','clearTimeout','performance']});
  const ended=vi.fn();
  try {
    const timing=auctionTiming(auction.starts_at,auction.ends_at,auction.server_time)!;
    const close=observeAuctionEnd(timing.millisecondsUntilEnd,200,ended);
    vi.advanceTimersByTime(799);
    expect(ended).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(ended).toHaveBeenCalledTimes(1);
    close();
    const alreadyEnded=vi.fn();
    observeAuctionEnd(timing.millisecondsUntilEnd,1000,alreadyEnded)();
    expect(alreadyEnded).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5000);
    expect(ended).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});
