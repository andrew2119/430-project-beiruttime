import { afterEach, describe, expect, it, vi } from 'vitest';
import { emptyDraft, dollars, amount, criteria, fromQuery, fromSaved, makeCommand, searchHref } from '../../../../web/features/saved-searches/state';
import { clearPublicDraft, holdPublicDraft, takePublicDraft } from '../../../../web/features/saved-searches/intent';
import { en, ar } from '../../../../web/features/saved-searches/copy';

afterEach(()=>{clearPublicDraft();vi.useRealTimers();});
describe('exact filters and public intent',()=>{
  it('accepts exact dollars in either digit system and preserves a one-cent boundary',()=>{
    expect(dollars('٥٠٠٠٫٠١')).toBe(500001);expect(dollars('5000.01')).toBe(500001);expect(dollars('')).toBeNull();expect(dollars('0')).toBe(0);
    expect(amount(8999999999999999)).toBe('89999999999999.99');expect(dollars(amount(8999999999999999))).toBe(8999999999999999);
    for(const value of ['1.001','-1','Infinity','1e2','90000000000000.01'])expect(()=>dollars(value)).toThrow();
  });
  it('keeps invalid imported criteria visible and prevents a broad replacement save',()=>{
    for(const query of ['q=Cedar&min_minor=bad','min_minor=1.5','currency=EUR','sale_mode=bad','sort=bad']){
      const draft=fromQuery(new URLSearchParams(query));expect(draft.importInvalid).toBe(true);expect(()=>criteria({...draft,name:'Search'})).toThrow();
    }
    const raw=fromQuery(new URLSearchParams('q=Cedar&min_minor=bad&currency=EUR'));
    expect(raw.q).toBe('Cedar');expect(raw.minimum).toBe('bad');expect(raw.importedCurrency).toBe('EUR');
    expect(fromQuery(new URLSearchParams('q=ساعة&min_minor=1')).minimum).toBe('0.01');
  });
  it('keeps immutable criteria and exact operation reference through both languages',()=>{
    const draft={...emptyDraft,name:'ساعة Cedar ⌚'.repeat(3),q:'ساعة Cedar ⌚',minimum:'١٠٫٠١',maximum:'20',alerts:true};
    const body=makeCommand(draft),serialized=JSON.stringify(body);
    for(const copy of [en,ar,en]){expect(copy.save).toBeTruthy();expect(JSON.stringify(body)).toBe(serialized);expect(body.operation_id).toBe(body.operation_id);}
    const restored=fromSaved({id:body.subject_id,revision:1,name:draft.name,criteria:body.criteria,alerts_enabled:true,state:'saved',created_at:'2026-11-17T12:00:00Z'});
    expect(criteria(restored)).toEqual(body.criteria);expect(searchHref(body.criteria)).toContain('min_minor=1001');
  });
  it('survives the public-to-member remount exactly once and refuses private data',()=>{
    const draft={...emptyDraft,name:'بحث ⌚ Cedar',minimum:'٥٫٠١',alerts:true};
    holdPublicDraft(draft);expect(takePublicDraft(null)).toBeNull();expect(takePublicDraft('current-member')).toEqual(draft);expect(takePublicDraft('next-member')).toBeNull();
    holdPublicDraft({...draft,id:'private',revision:4});expect(takePublicDraft('next-member')).toBeNull();
    holdPublicDraft(draft);clearPublicDraft();expect(takePublicDraft('member')).toBeNull();
    vi.useFakeTimers();holdPublicDraft(draft);vi.advanceTimersByTime(300001);expect(takePublicDraft('member')).toBeNull();
  });
  it('publishes complete matching dictionary keys',()=>{expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());for(const value of Object.values(ar))expect(value.trim()).not.toBe('');});
});
