import { afterEach, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import BuyerAuctionPage from '../app/(buyer)/buyer/auctions/[listingId]/page';
import { BuyerAuctionView } from '../features/proxy-bid/proxy-bid';
import { PageFrame, PageHeader } from '../shell/foundation/page';
import en from '../features/proxy-bid/en.json';
import ar from '../features/proxy-bid/ar.json';

type Header = ReactElement<{title:string;lead:string;actions:ReactElement<{href:string;children:string}>}>;
type Slot = ReactElement<{locale:'en'|'ar';resourceId:string}>;
const state = vi.hoisted(() => ({locale:'en'}));
vi.mock('@/shell/locale', () => ({getLocale:async () => state.locale}));
afterEach(() => {state.locale='en';});

it('fresh route copy updates the auction header, recovery link and slot props with the same identity', async () => {
  const listingId='12345678-1234-1234-1234-123456789012';
  const render = async () => {
    const route=await BuyerAuctionPage({params:Promise.resolve({listingId})});
    expect(route.type).toBe(BuyerAuctionView);
    expect(route.props.listingId).toBe(listingId);
    // The route now returns a pure view; leave its stateful auction slot uncalled.
    const frame=BuyerAuctionView(route.props);
    expect(frame.type).toBe(PageFrame);
    expect(frame.props.children).toHaveLength(2);
    const [header,slot]=frame.props.children as [Header,Slot];
    expect(header.type).toBe(PageHeader);
    return {route,frame,header,recovery:header.props.actions,slot};
  };
  const before=await render();
  expect(before.route.props.locale).toBe('en');
  expect(before.header.props.title).toBe(en.auctionBidding);
  expect(before.header.props.lead).toBe(en.privacy);
  expect(before.recovery.props.href).toBe('/en/buyer');
  expect(before.recovery.props.children).toBe(en.backToBuying);
  expect(before.slot.props.locale).toBe('en');
  expect(before.slot.props.resourceId).toBe(listingId);
  state.locale='ar';
  const after=await render();
  expect(after.route.props.locale).toBe('ar');
  expect(after.header.props.title).toBe(ar.auctionBidding);
  expect(after.header.props.lead).toBe(ar.privacy);
  expect(after.recovery.props.href).toBe('/ar/buyer');
  expect(after.recovery.props.children).toBe(ar.backToBuying);
  expect(after.slot.props.locale).toBe('ar');
  expect(after.slot.props.resourceId).toBe(listingId);
  for (const name of ['route','frame','header','recovery','slot'] as const) {
    expect(after[name].type).toBe(before[name].type);
    expect(after[name].key).toBe(before[name].key);
  }
});
