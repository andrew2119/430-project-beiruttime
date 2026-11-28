import { afterEach, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import BuyerAuctionPage from '../app/(buyer)/buyer/auctions/[listingId]/page';
import { BuyerAuctionView } from '../features/proxy-bid/proxy-bid';
import en from '../features/proxy-bid/en.json';
import ar from '../features/proxy-bid/ar.json';

const state = vi.hoisted(() => ({locale:'en'}));
vi.mock('@/shell/locale', () => ({getLocale:async () => state.locale}));
// The root layout feeds the locale context from the same locale read, so both follow one value here.
vi.mock('@/shell/locale-context', async importOriginal => ({...await importOriginal<typeof import('@/shell/locale-context')>(), useLocale:() => state.locale}));
afterEach(() => {state.locale='en';});

it('fresh route copy updates the auction header, recovery link and slot props with the same identity', async () => {
  const listingId='12345678-1234-1234-1234-123456789012';
  const auctionId='87654321-4321-4321-4321-210987654321';
  const render = async () => {
    const route=await BuyerAuctionPage({params:Promise.resolve({listingId}), searchParams:Promise.resolve({auction:auctionId})});
    expect(route.type).toBe(BuyerAuctionView);
    const props=route.props as Parameters<typeof BuyerAuctionView>[0];
    const view=BuyerAuctionView(props);
    return {props, children:(view.props as {children:[ReactElement<{title:string;lead:string;actions:ReactElement<{href:string}>}>,ReactElement<{locale:string;resourceId:string;auctionId?:string}>,ReactElement]}).children};
  };
  const before=await render();
  expect(before.props.locale).toBe('en');
  expect(before.children[0].props.title).toBe(en.auctionBidding);
  expect(before.children[1].props.locale).toBe('en');
  state.locale='ar';
  const after=await render();
  expect(after.props).toEqual({locale:'ar', listingId, auctionId});
  expect(after.children[0].props.title).toBe(ar.auctionBidding);
  expect(after.children[0].props.lead).toBe(ar.privateMaximum);
  expect(after.children[0].props.actions.props.href).toBe('/ar/buyer');
  expect(after.children[1].props.locale).toBe('ar');
  expect(after.children[1].props.resourceId).toBe(listingId);
  expect(after.children[1].props.auctionId).toBe(auctionId);
  for (let index=0; index<before.children.length; index++) {
    expect(after.children[index].type).toBe(before.children[index].type);
    expect(after.children[index].key).toBe(before.children[index].key);
  }
});
