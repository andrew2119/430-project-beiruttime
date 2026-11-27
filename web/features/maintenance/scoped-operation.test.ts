import {describe,expect,it} from 'vitest';
import {operationPath,originalOutcome,type OperationBinding} from './scoped-operation';

const buyer:OperationBinding={kind:'preference',operation_id:'original',owner:'buyer',record:'request-a',organization:'shop',
  expected_revision:1,source_revision:3};

describe('scoped maintenance recovery',()=>{
  it('still checks the original operation after another watch opens and preferences are superseded',()=>{
    const original={operation_id:'original',buyer_id:'buyer',request_id:'request-a',organization_id:'shop',
      request_revision:3,expected_revision:1,revision:2,opening_permitted:true,no_polish:true};
    expect(operationPath(buyer)).toContain('request-a/opening-consent/operations/original');
    expect(originalOutcome({...original,request_id:'request-b'},buyer)).toBeNull();
    expect(originalOutcome({...original,operation_id:'later',expected_revision:2,revision:3,opening_permitted:false},buyer)).toBeNull();
    expect(originalOutcome(original,buyer)).toBe('recorded');
    expect(originalOutcome({state:'closed',operation_id:'original',request_id:'request-a',buyer_id:'buyer'},buyer)).toBe('closed');
  });

  it('keeps only scope when a diagnosis form is removed, then verifies the same receipt on return',()=>{
    const diagnosis:OperationBinding={...buyer,kind:'diagnosis',owner:'assessor',record:'case',source_revision:7};
    const result={state:'assessed',operation_id:'original',actor_id:'assessor',case_id:'case',organization_id:'shop',
      reviewed_intake:{intake_revision:7},expected_revision:1,revision:2,diagnosis:'Private assessed finding'};
    expect(operationPath(diagnosis)).toBe('service-cases/case/diagnosis/operations/original?organization_id=shop');
    expect(originalOutcome({...result,actor_id:'reassigned'},diagnosis)).toBeNull();
    expect(originalOutcome({...result,reviewed_intake:{intake_revision:8}},diagnosis)).toBeNull();
    expect(originalOutcome(result,diagnosis)).toBe('recorded');
    expect(Object.keys(diagnosis).sort()).toEqual(['expected_revision','kind','operation_id','organization','owner','record','source_revision']);
  });
});
