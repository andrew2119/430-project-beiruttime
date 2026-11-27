import { afterEach, describe, expect, it } from 'vitest';
import { draftMemoryEpoch, purge, recall, remember, type DraftMemory } from './memory';
const draft:DraftMemory={owner:'buyer-scope',id:'draft',revision:2,submittedRequestId:'immutable-request',dirty:false,form:{configuration_id:'configuration',configuration_revision:7,brand_id:'brand',kind:'customization',watch_context:'owned_watch',watch_reference:'Sample watch',scope_intent:'Sample scope',notes:'Sample notes',options:{}}};
afterEach(purge);
describe('private request memory',()=>{
  it('retains the authoritative submitted pointer independently of readiness reads',()=>{
    remember(draft,draftMemoryEpoch());
    expect(recall(draft.owner)?.submittedRequestId).toBe('immutable-request');
  });
  it('does not leak a submitted pointer or notes across account boundaries',()=>{
    remember(draft,draftMemoryEpoch());
    expect(recall('other-buyer')).toBeNull();
    expect(recall(draft.owner)).toBeNull();
  });
  it('fences late writes after access changes',()=>{
    const old=draftMemoryEpoch();purge();remember(draft,old);
    expect(recall(draft.owner)).toBeNull();
  });
});
