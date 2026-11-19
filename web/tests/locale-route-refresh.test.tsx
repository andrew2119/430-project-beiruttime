import { afterEach, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import BuyerAuctionPage from '../app/(buyer)/buyer/auctions/[listingId]/page';
import en from '../features/proxy-bid/en.json';
import ar from '../features/proxy-bid/ar.json';

const state = vi.hoisted(() => ({locale:'en'}));
vi.mock('@/shell/locale', () => ({getLocale:async () => state.locale}));
afterEach(() => {state.locale='en';});

it('fresh route copy updates the auction header, recovery link and slot props with the same identity', async () => {
  const listingId='12345678-1234-1234-1234-123456789012';
  const render = async () => {
    const route=await BuyerAuctionPage({params:Promise.resolve({listingId})});
    return (route.props.children as ReactElement<{children:[ReactElement<{title:string;count:string;lead:ReactElement<{href:string}>}>,ReactElement<{locale:string;resourceId:string}>]}>).props.children;
  };
  const before=await render();
  expect(before[0].props.title).toBe(en.auctionBidding);
  expect(before[1].props.locale).toBe('en');
  state.locale='ar';
  const after=await render();
  expect(after[0].props.title).toBe(ar.auctionBidding);
  expect(after[0].props.count).toBe(ar.privacy);
  expect(after[0].props.lead.props.href).toBe('/ar/buyer');
  expect(after[1].props.locale).toBe('ar');
  expect(after[1].props.resourceId).toBe(listingId);
  for (let index=0; index<before.length; index++) {
    expect(after[index].type).toBe(before[index].type);
    expect(after[index].key).toBe(before[index].key);
  }
});
