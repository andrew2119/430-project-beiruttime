import {renderToStaticMarkup} from 'react-dom/server';
import {expect,it,vi} from 'vitest';
import BidSlot from './bid-slot';
import ProxyBidSlot from '@/features/proxy-bid/proxy-bid';

const source=vi.hoisted(()=>({read:vi.fn(),retry:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:source.read}));
vi.mock('@/features/identity/session',()=>({
  useSession:()=>null,useSessionState:()=> 'signed-out',refreshSession:vi.fn(),signInHref:()=>'/en/account',
}));
vi.mock('./operation-scope',()=>({useOperationScope:()=>vi.fn()}));

it('keeps the manual bid and maximum shortcut on the same listing answer across close',()=>{
  const listing='00000000-0000-4000-8000-000000000001';
  const lot={id:'00000000-0000-4000-8000-000000000002',listing_id:listing,revision:1,status:'live',mode:'bidding',
    starts_at:'2030-01-01T10:00:00Z',ends_at:'2030-01-02T10:00:00Z',server_time:'2030-01-01T11:00:00Z',
    currency:'USD',opening_minor:400000,current_minor:0,next_minimum_minor:400000,high_value_minor:1000000,
    increment_bands:[{from_minor:0,step_minor:10000}]};
  function draw(auction:typeof lot) {
    source.read.mockClear().mockImplementation(read=>read.key[0]==='listing-auction'
      ?{data:{items:[auction]},dataUpdatedAt:1,refetch:source.retry}
      :{data:{items:[]},refetch:source.retry});
    return renderToStaticMarkup(<><BidSlot locale="en" resourceId={listing}/><ProxyBidSlot locale="en" resourceId={listing}/></>);
  }
  expect(draw(lot)).toContain('Private maximum bid');
  const keys=source.read.mock.calls.map(([read])=>read.key).filter(key=>key[0]==='listing-auction');
  expect(keys).toEqual(Array.from({length:2},()=>['listing-auction',listing]));
  expect(draw({...lot,status:'ended',server_time:lot.ends_at})).not.toContain('Private maximum bid');
  expect(source.retry).not.toHaveBeenCalled();
});
