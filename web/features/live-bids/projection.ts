import type { AuctionSnapshot } from '@contracts/contracts-catalog/discovery';
// HTTP snapshots are canonical. Poll gaps never become invented bids.
export function reconcileSnapshot(current: AuctionSnapshot|null, next: AuctionSnapshot): AuctionSnapshot|null {
  if(!Number.isSafeInteger(next.revision)||!Number.isSafeInteger(next.last_sequence)||!Number.isSafeInteger(next.end_version)||next.revision<1||next.last_sequence<0||next.end_version<1||!Number.isFinite(Date.parse(next.server_time))||!Number.isFinite(Date.parse(next.ends_at))) return null;
  if(current&&(next.auction_id!==current.auction_id||next.listing_id!==current.listing_id||next.revision<current.revision||next.last_sequence<current.last_sequence||next.end_version<current.end_version)) return null;
  const sequences=new Set<number>();
  for(const bid of next.bids) {
    if(!Number.isSafeInteger(bid.sequence)||bid.sequence<1||bid.sequence>next.last_sequence||sequences.has(bid.sequence))return null;
    sequences.add(bid.sequence);
  }
  if(current&&next.ends_at!==current.ends_at) return null;
  if(current&&next.revision===current.revision&&(next.last_sequence!==current.last_sequence||next.end_version!==current.end_version||next.current_price.amount!==current.current_price.amount||next.current_price.currency!==current.current_price.currency))return null;
  return next;
}
export function displayedPrice(snapshot: AuctionSnapshot) {
  const opening=!!snapshot.opening_price&&/^0(?:\.0+)?$/.test(snapshot.current_price.amount);
  return { opening, money: opening?snapshot.opening_price!:snapshot.current_price };
}
export type ServerClock = { serverMs: number; receivedAt: number; roundTripMs: number };
export function secondsRemaining(endsAt: string, clock: ServerClock, monotonicNow: number): number {
  const authoritativeNow=clock.serverMs+Math.max(0,clock.roundTripMs)/2+Math.max(0,monotonicNow-clock.receivedAt);
  return Math.max(0,Math.ceil((Date.parse(endsAt)-authoritativeNow)/1000));
}
export function countdown(seconds: number): string {
  const hours=Math.floor(seconds/3600), minutes=Math.floor((seconds%3600)/60), remainder=seconds%60;
  return `${String(hours).padStart(2,'0')}:${String(minutes).padStart(2,'0')}:${String(remainder).padStart(2,'0')}`;
}
