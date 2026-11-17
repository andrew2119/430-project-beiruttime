import { describe, it, expect } from 'vitest';
import source from '../../../../packages/contracts-service/finish/fixtures/source.json';
import command from '../../../../packages/contracts-service/finish/fixtures/command.json';
import { makeCommand, permitsIntervention, centsToDollars, validateDetail, validateResult, recoverOrRecord } from '../../../../web/features/finish/model';
import { copy } from '../../../../web/features/finish/copy';
import type { Detail } from '../../../../packages/contracts-service/finish';
const detail={source,revision:0,choices:[]} as Detail;
describe('exact finish choices',()=>{
  it('has no implicit choice',()=>expect(()=>makeCommand(detail,{},command.operation_id)).toThrow());
  it('matches the deterministic contract',()=>expect(makeCommand(detail,{[source.areas[0].area_id]:'consent'},command.operation_id)).toEqual(command));
  it('keeps command data independent of display language',()=>{
    const choices={[source.areas[0].area_id]:'no_polish'} as const;
    const pending=makeCommand(detail,choices,command.operation_id);
    for(const locale of ['en','ar'] as const) {
      expect(copy[locale].no_polish).toBeTruthy();
      expect(makeCommand(detail,choices,pending.operation_id)).toEqual(pending);
    }
  });
  it('blocks unsafe action but allows preservation',()=>{
    for(const patch of [{plating:'thin'},{coating:'unknown'},{engraving:'present'},{original:'unknown'},{desired:'mirror'},{suitable:false},{material_known:false},{preservation_assessed:false}] as const) {
      const area={...detail.source.areas[0],...patch};
      expect(permitsIntervention(area)).toBe(false);
      const altered={...detail,source:{...detail.source,areas:[area]}};
      expect(()=>makeCommand(altered,{[area.area_id]:'consent'},command.operation_id)).toThrow();
      expect(makeCommand(altered,{[area.area_id]:'no_polish'},command.operation_id).choices[0].decision).toBe('no_polish');
    }
  });
  it('bounds areas rather than truncating a large scope',()=>{
    for(const count of [0,1000]) expect(()=>makeCommand({...detail,source:{...detail.source,areas:Array.from({length:count},()=>detail.source.areas[0])}},{},command.operation_id)).toThrow();
  });
  it('rejects malformed and mismatched private answers',()=>{
    expect(validateDetail(detail,source.subject_id)).toEqual(detail);
    expect(()=>validateDetail({...detail,source:{...source,areas:null}},source.subject_id)).toThrow();
    expect(()=>validateDetail(detail,command.watch_id)).toThrow();
    expect(()=>validateResult({state:'recorded'},command)).toThrow();
  });
  it('formats exact cents without floating point rounding',()=>{
    expect(centsToDollars(1)).toBe('0.01');expect(centsToDollars(500000)).toBe('5000.00');
    expect(()=>centsToDollars(Infinity)).toThrow();
  });
});

describe('retained terms',()=>{
  it('requires both languages and a support destination',()=>{
    for(const key of ['fee_en','fee_ar','return_en','return_ar','assurance_en','assurance_ar','support_path']) {
      expect(()=>validateDetail({...detail,source:{...source,terms:{...source.terms,[key]:''}}},source.subject_id)).toThrow();
    }
  });
});

describe('uncertain operation recovery',()=>{
  it('recovers a recorded operation before resubmitting changed source',async()=>{
    let writes=0;
    expect(await recoverOrRecord(async()=>({state:'recorded',operation_id:command.operation_id}),async()=>{writes++;throw new Error('stale');},()=>false)).toEqual({state:'recorded',operation_id:command.operation_id});
    expect(writes).toBe(0);
  });
  it('only retries a confirmed missing receipt and retains uncertainty otherwise',async()=>{
    let writes=0;
    const write=async()=>{writes++;return command.operation_id;};
    await expect(recoverOrRecord(async()=>{throw new Error('unavailable');},write,()=>false)).rejects.toThrow('unavailable');
    expect(writes).toBe(0);
    expect(await recoverOrRecord(async()=>{throw new Error('missing');},write,()=>true)).toBe(command.operation_id);
    expect(writes).toBe(1);
  });
});
