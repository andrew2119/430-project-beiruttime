import { describe,it,expect } from 'vitest';
import { RefundDraft, dollarsToMinor, unavailablePort } from './model';
import { copy } from './copy';
const binding={subject_id:'order',watch_id:'watch',actor_id:'operator',organization_id:'business',
  expected_revision:1,source_revision:1,quote_id:'quote',quote_revision:1,policy_revision:1,basis_id:'basis'};
describe('refund draft',()=>{
  it.each([['125.50',12550],['١٢٥٫٥٠',12550],['۱۲۵.۵۰',12550],['0.01',1],['90000000000000',9000000000000000]])('parses exact dollars %s',(input,expected)=>{
    expect(dollarsToMinor(input)).toBe(expected);
  });
  it.each(['','0','-1','1.001','1e3','Infinity','1,000','01','90000000000000.01'])('rejects %s',input=>{
    expect(dollarsToMinor(input)).toBeNull();
  });
  it('keeps exact text, command and pending reference across language and retry',()=>{
    const draft=new RefundDraft();draft.amount='١٢٥٫٥٠';
    const command=draft.prepare(binding,'reference');
    for (const locale of ['ar','en','ar'] as const) {
      expect(copy[locale].title).toBeTruthy();
      expect(draft.prepare({...binding,expected_revision:9},'another')).toBe(command);
      expect(draft.amount).toBe('١٢٥٫٥٠');
    }
  });
  it('rejects a foreign or malformed result',()=>{
    const draft=new RefundDraft();draft.amount='1';const command=draft.prepare(binding,'reference')!;
    const result={...command,state:'confirmed' as const,revision:2,pending_reason:null,next_actor:null,next_review_at:null,simulated:true as const};
    expect(()=>draft.accept({...result,operation_id:'other'})).toThrow('unavailable');
    draft.accept(result);expect(draft.operation?.state).toBe('confirmed');
  });
  it('keeps the command when the provider is unavailable',async()=>{
    const draft=new RefundDraft();draft.amount='5000';const command=draft.prepare(binding,'reference')!;
    await expect(unavailablePort.request(command,new AbortController().signal)).rejects.toThrow('unavailable');
    expect(draft.command).toBe(command);
  });
  it('reloads a definitively rejected request before an explicitly new revision',()=>{
    const draft=new RefundDraft();draft.setAmount('100');draft.begin(binding,'first');
    draft.fail('stale',true);draft.finish();expect(draft.read().rejected).toBe(true);
    draft.reviewRejected();expect(draft.command).toBeNull();expect(draft.amount).toBe('100');
    expect(draft.begin({...binding,expected_revision:2},'second')?.expected_revision).toBe(2);
  });
  it('cannot discard uncertainty through a later permission or stale rejection',()=>{
    const draft=new RefundDraft();draft.setAmount('100');const original=draft.begin(binding,'first');
    draft.fail('pending');draft.finish();draft.fail('stale',true);
    draft.reviewRejected();expect(draft.command).toBe(original);expect(draft.read().rejected).toBe(false);
  });
  it('has complete matching language recovery keys',()=>{
    expect(Object.keys(copy.ar).sort()).toEqual(Object.keys(copy.en).sort());
    expect(Object.values(copy.ar).every(Boolean)).toBe(true);
  });
});
