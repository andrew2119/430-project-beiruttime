import {expect,it,vi} from 'vitest';
import {PageReadProvider} from '@/lib/page-speed/provider';
import {renderToStaticMarkup} from 'react-dom/server';
import BuyerWorkspace from './buyer-workspace';
import {BuyerAuctionView} from './proxy-bid';
import {LocaleContext} from '@/shell/locale-context';

vi.mock('./session',()=>({useBuyerSession:()=>({
  state:'authenticated',signedIn:true,fingerprint:'test-buyer',subjectId:'test-buyer',
  organizationId:null,roles:['buyer'],
})}));

it('opens both buyer views under the shared read scope',()=>{
  const workspace=renderToStaticMarkup(<PageReadProvider><BuyerWorkspace/></PageReadProvider>);
  expect(workspace).toContain('My buying workspace');
  expect(workspace).toContain('Loading your activity');
  expect(workspace).not.toContain('Temporarily unavailable');
  const lot=renderToStaticMarkup(<PageReadProvider><BuyerAuctionView locale="en" listingId="test-listing"/></PageReadProvider>);
  expect(lot).toContain('Auction bidding');
  expect(lot).toContain('Loading your activity');
  expect(lot).not.toContain('Temporarily unavailable');
});

it.each(['en','ar'] as const)('renders the buyer-route language control from %s',locale=>{
  for(const page of [<BuyerWorkspace key="workspace"/>,<BuyerAuctionView key="auction" locale={locale} listingId="test-listing"/>]) {
    const html=renderToStaticMarkup(<LocaleContext value={locale}><PageReadProvider>{page}</PageReadProvider></LocaleContext>);
    expect(html).toContain(`aria-label="${locale==='ar'?'اللغة':'Language'}"`);
    expect(html).toContain('<span lang="en">English</span>');
    expect(html).toContain('<span lang="ar">العربية</span>');
  }
});

vi.mock('next/navigation',()=>({useRouter:()=>({refresh:vi.fn()}),usePathname:()=>'/en/buyer'}));

it('mounts the registered watch shortcut under the current read scope',async()=>{
  const {default:Slot}=await import('./proxy-bid');
  expect(renderToStaticMarkup(<PageReadProvider><Slot locale="en" resourceId="test-listing"/></PageReadProvider>)).toBe('');
});
