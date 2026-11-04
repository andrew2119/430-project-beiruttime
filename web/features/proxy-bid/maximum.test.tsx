import {beforeEach,describe,it,expect,vi} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {MaximumForm} from './proxy-bid';
const session=vi.hoisted(()=>({signedIn:true,fingerprint:'buyer-A',roles:['buyer']}));
vi.mock('./session',()=>({useBuyerSession:()=>session,authenticatedRequest:vi.fn(),signInHref:(next:string,locale:string)=>`/${locale}/account?next=${encodeURIComponent(next)}`}));
beforeEach(()=>{session.signedIn=true;session.roles=['buyer'];});
describe('maximum form capability boundary',()=>{
  it('renders permission denial rather than a fabricated buyer or submit control',()=>{
    session.roles=['operator'];
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Your current account cannot use buyer actions.');expect(html).not.toContain('<input');
  });
  it('preserves the non-secret intended auction route when signing in',()=>{
    session.signedIn=false;
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} signInNext="/buyer/auctions/watch-A" getQuote={vi.fn()}/>);
    expect(html).toContain('/en/account?next=%2Fbuyer%2Fauctions%2Fwatch-A');expect(html).not.toContain('<input');
  });
  it('never enables submission without the current bound pricing capability',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}}/>);
    expect(html).toContain('Temporarily unavailable');expect(html).not.toContain('<input');expect(html).not.toContain('type="submit"');
  });
  it('requires review before confirmation and keeps secret inputs unpersisted',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="USD" locale="en" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('Review maximum and fees');expect(html).toContain('inputMode="decimal"');
    expect(html).toContain('autoComplete="off"');expect(html).not.toContain('buyer-A');
    expect(html).not.toContain('Set private maximum</button>');
  });
  it('uses Arabic copy and isolated currency without a second form implementation',()=>{
    const html=renderToStaticMarkup(<MaximumForm auctionId="auction-A" revision={1} currency="LBP" locale="ar" onRefresh={()=>{}} getQuote={vi.fn()}/>);
    expect(html).toContain('مراجعة الحد الأقصى والرسوم');expect(html).toContain('<bdi dir="ltr">LBP</bdi>');
  });
});
