import { describe, expect, it } from 'vitest';
import { blank, complete, commandLines, makeCommand, type Context } from './draft';
import { messages } from './messages';
describe('quality draft',()=>{
  it('requires explicit findings and outcomes',()=>{
    const draft=blank('line');
    expect(complete([draft])).toBe(false);
    for(const field of ['condition','fit','returned_parts'] as const) draft[field]={actual:'قياس 175 mm 👩🏽‍🔧',result:'pass'};
    draft.tests.tests={actual:'actual test',result:'pass'};
    expect(complete([draft])).toBe(true);
    expect(commandLines([draft])[0].fit.actual).toBe('قياس 175 mm 👩🏽‍🔧');
    draft.tests.tests={actual:'actual test',result:'pass'};
    const context: Context={line_ids:['line'],test_keys:{line:['tests']},job_id:'job',actor_id:'reviewer',organization_id:'business',watch_id:'watch',expected_revision:0,scope_revision:1,work_revision:1,assignment_revision:1,quote_id:'quote',quote_revision:1,policy_revision:1};
    const pending=makeCommand(context,[draft],'same-operation');
    for(const locale of ['ar','en','ar'] as const) {
      expect(messages[locale].pending).toBeTruthy();
      expect(pending.operation_id).toBe('same-operation');
      expect(draft.fit.actual).toBe('قياس 175 mm 👩🏽‍🔧');
    }
  });
  it('retains rework and enforces source line scope',()=>{
    const draft=blank('line');
    for(const field of ['condition','fit','returned_parts'] as const) draft[field]={actual:'actual',result:'fail'};
    draft.tests.tests={actual:'failed test',result:'fail'};
    expect(commandLines([draft])[0].returned_parts.satisfactory).toBe(false);
    expect(()=>makeCommand({line_ids:['another']} as Context,[draft],'operation')).toThrow();
  });
  it('rejects findings that the record boundary rejects',()=>{
    const draft=blank('line');
    for(const field of ['condition','fit','returned_parts'] as const) draft[field]={actual:'measured',result:'pass'};
    draft.tests.tests={actual:' measured 175 mm',result:'pass'};
    expect(complete([draft])).toBe(false);
    expect(()=>commandLines([draft])).toThrow('incomplete');
    draft.tests.tests.actual='measured 175 mm';
    expect(complete([draft])).toBe(true);
  });
  it('has identical recovery message keys',()=>expect(Object.keys(messages.ar)).toEqual(Object.keys(messages.en)));
});
