import { describe, expect, it } from 'vitest';
import type { AuctionSnapshot } from '@contracts/contracts-catalog/discovery';
import { countdown, displayedPrice, reconcileSnapshot, secondsRemaining } from './projection';
const snapshot:AuctionSnapshot={auction_id:'auction',listing_id:'watch',revision:2,last_sequence:1,current_price:{amount:'4300.00',currency:'USD'},server_time:'2026-01-01T00:00:00Z',ends_at:'2026-01-01T00:01:00Z',end_version:1,status:'open',bids:[{sequence:1,bidder_label:'Bidder A19F',amount:{amount:'4300.00',currency:'USD'},accepted_at:'2026-01-01T00:00:00Z'}],history_truncated:false};
describe('canonical auction projection',()=>{
  it('recovers a sequence gap using a full snapshot',()=>{
    const next={...snapshot,revision:9,last_sequence:8};
    expect(reconcileSnapshot(snapshot,next)).toEqual(next);
    expect(reconcileSnapshot(next,snapshot)).toBeNull();
  });
  it('allows duplicate snapshots without creating duplicate history',()=>{
    expect(reconcileSnapshot(snapshot,snapshot)?.bids).toHaveLength(1);
    expect(reconcileSnapshot(snapshot,{...snapshot,bids:[snapshot.bids[0],snapshot.bids[0]]})).toBeNull();
  });
  it('rejects older end versions and unexplained deadline changes',()=>{
    expect(reconcileSnapshot(snapshot,{...snapshot,end_version:0})).toBeNull();
    expect(reconcileSnapshot(snapshot,{...snapshot,ends_at:'2026-01-01T00:02:00Z'})).toBeNull();
    expect(reconcileSnapshot(snapshot,{...snapshot,revision:3,end_version:2,ends_at:'2026-01-01T00:02:00Z'})).toBeNull();
  });
  it('rejects changed price or sequence under an unchanged canonical revision',()=>{
    expect(reconcileSnapshot(snapshot,{...snapshot,current_price:{amount:'4400.00',currency:'USD'}})).toBeNull();
    expect(reconcileSnapshot(snapshot,{...snapshot,last_sequence:2})).toBeNull();
  });
  it('labels the opening price without fabricating a current accepted bid',()=>{
    const empty={...snapshot,last_sequence:0,bids:[],current_price:{amount:'0.00',currency:'USD' as const},opening_price:{amount:'4000.00',currency:'USD' as const}};
    expect(displayedPrice(empty)).toEqual({opening:true,money:empty.opening_price});
    expect(displayedPrice({...snapshot,opening_price:empty.opening_price})).toEqual({opening:false,money:snapshot.current_price});
    expect(reconcileSnapshot(snapshot,{...snapshot,revision:3,last_sequence:2})).not.toBeNull();
  });
  it('uses a monotonic server anchor, not the device wall clock',()=>{
    const clock={serverMs:Date.parse(snapshot.server_time),receivedAt:1000,roundTripMs:0};
    expect(secondsRemaining(snapshot.ends_at,clock,59999+1000)).toBe(1);
    expect(secondsRemaining(snapshot.ends_at,clock,60000+1000)).toBe(0);
    expect(secondsRemaining(snapshot.ends_at,clock,60001+1000)).toBe(0);
    expect(secondsRemaining(snapshot.ends_at,{...clock,roundTripMs:1000},1000)).toBe(60);
    expect(countdown(90061)).toBe('25:01:01');
  });
});
