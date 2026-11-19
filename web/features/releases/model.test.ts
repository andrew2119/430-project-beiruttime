import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dollars, operation, pending, preview, type Memory } from './model';
import { COPY } from './copy';
import { conditions, type Command } from '@contracts/contracts-orders/releases';
const fixtures = JSON.parse(readFileSync(new URL('../../../packages/contracts-orders/releases/fixtures.json',import.meta.url),'utf8'));
const command = fixtures.command as Command;
describe('private release contract',()=>{
  it('keeps exact cents and reconciles retained economics',()=>{
    expect(dollars(475000)).toBe('4750.00');expect(dollars(1)).toBe('0.01');
    expect(dollars(Number.MAX_SAFE_INTEGER)).toBe('90071992547409.91');
    expect(operation(fixtures.success,command).net_minor).toBe(475000);
    for (const v of [-1,Infinity,NaN,0.1]) expect(()=>dollars(v)).toThrow();
  });
  it('rejects stale, foreign and malformed acknowledgements',()=>{
    for (const change of [{actor_id:fixtures.source.seller_id},{organization_id:fixtures.source.seller_id},
      {operation_id:fixtures.source.watch_id},{recipient_revision:99},{quote_revision:99},
      {simulated:false},{net_minor:500000},{state:'paid_out',pending_reason:'response_unknown'},
      {next_review_at:'2026-11-01T12:00:00'},{gross_minor:Infinity},{missing:['other']},
      {gross_minor:null,fee_minor:null,net_minor:null}]) {
      expect(()=>operation({...fixtures.success,...change},command)).toThrow();
    }
  });
  it('retains the exact action for lost response and both languages',()=>{
    const memory:Memory = {command,result:null};
    expect(pending(memory)).toBe(true);
    for (const locale of ['ar','en','ar','en'] as const) {
      expect(COPY[locale].pendingBody.length).toBeGreaterThan(20);
      expect(memory.command).toBe(command);
      expect(JSON.stringify(memory.command)).toBe(JSON.stringify(fixtures.command));
    }
    expect(pending({command,result:fixtures.lost_response})).toBe(true);
    expect(pending({command,result:fixtures.success})).toBe(false);
  });
  it('validates current preview bindings without using it as payout authority',()=>{
    const value = {snapshot:fixtures.source,missing:[],closes_at:fixtures.now,simulated:true};
    expect(preview(value,command.subject_id,null).snapshot).toEqual(fixtures.source);
    expect(()=>preview(value,command.watch_id,null)).toThrow();
    expect(()=>preview(value,command.subject_id,command.watch_id)).toThrow();
    expect(()=>preview({...value,snapshot:{...fixtures.source,principal_minor:NaN}},command.subject_id,null)).toThrow();
  });
  it('has complete recovery and missing-condition copy in both languages',()=>{
    for (const locale of ['en','ar'] as const) {
      expect(Object.keys(COPY[locale].reasons).sort()).toEqual([...conditions].sort());
      expect(Object.values(COPY[locale]).every(value=>typeof value !== 'string' || value.length > 0)).toBe(true);
    }
  });
});

it('discovers a scoped durable operation after reopening the order',async()=>{
  const { restoredOperation, commandOf } = await import('./model');
  const result = restoredOperation(fixtures.transfer_pending,command.operation_id,command.actor_id,null,command.subject_id);
  expect(commandOf(result)).toEqual(command);
  expect(pending({command:commandOf(result),result})).toBe(true);
  expect(()=>restoredOperation(result,command.operation_id,command.watch_id,null,command.subject_id)).toThrow();
  expect(()=>restoredOperation(result,command.operation_id,command.actor_id,null,command.watch_id)).toThrow();
});
