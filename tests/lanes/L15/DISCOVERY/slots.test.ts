import { describe, expect, it } from 'vitest';
import { loadWatchSlots, slotMountKey } from '../../../../web/features/discovery/slot-loader';
import type { SlotContext } from '../../../../web/registry-types';

describe('independent sale slot composition',()=>{
  it('isolates failed loading, preserves order, and recovers on another load',async()=>{
    const Visible=()=>null;
    const loaded=await loadWatchSlots([{id:'first',load:async()=>({default:Visible})},{id:'second',load:async()=>{throw new Error('Unavailable');}}]);
    expect(loaded.map(slot=>slot.id)).toEqual(['first','second']);
    expect(loaded[0].component).toBe(Visible);
    expect(loaded[1].component).toBeNull();
    expect((await loadWatchSlots([{id:'second',load:async()=>({default:Visible})}]))[0].component).toBe(Visible);
  });
  it('passes denied and stale states through the owner without fabricating success',async()=>{
    const Owner=({accessFingerprint}:SlotContext)=>accessFingerprint==='current'?'Available':accessFingerprint==='revoked'?'Denied':'Unavailable';
    const [slot]=await loadWatchSlots([{id:'sale',load:async()=>({default:Owner})}]);
    for(const [accessFingerprint,text] of [['current','Available'],['revoked','Denied'],['stale','Unavailable']]) {
      expect(slot.component).toBe(Owner);
      expect(Owner({locale:'en',resourceId:'watch',accessFingerprint})).toBe(text);
    }
    expect(slotMountKey('sale','current')).not.toBe(slotMountKey('sale','revoked'));
    expect(slotMountKey('sale','current')).not.toBe(slotMountKey('sale','stale'));
    expect(slotMountKey('sale',null)).toBe('sale:public');
  });
});
