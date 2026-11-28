import { describe, expect, it } from 'vitest';
import { toggleComparison } from '../../../../web/features/discovery/compare';
import en from '../../../../web/features/discovery/en.json';
import ar from '../../../../web/features/discovery/ar.json';

describe('public selection and bilingual recovery',()=>{
  it('keeps three distinct watches and permits removal at the limit',()=>{
    let ids:string[]=[];
    for(const id of ['a','b','c','d'])ids=toggleComparison(ids,id);
    expect(ids).toEqual(['a','b','c']);
    expect(toggleComparison(ids,'b')).toEqual(['a','c']);
  });
  it('preserves long mixed text and identifiers through selection',()=>{
    const id='مرجع Watch ٣٦ ⌚'.repeat(40);
    expect(toggleComparison([],id)).toEqual([id]);
  });
  it('provides the same complete set of recovery and disclosure strings',()=>{
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    for(const value of Object.values(ar))expect(value.trim()).not.toBe('');
  });
});
