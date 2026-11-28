import { describe, expect, it } from 'vitest';
import { PendingCommand, reconcile } from '../../../../web/features/messages/operation';
import type { Command, Receipt } from '../../../../packages/contracts-comms/messages';
const body:Command={operation_id:'send-one',kind:'send',body:'ساعة ⌚ watch',expected_revision:1,source_revision:1,quote_revision:null,policy_revision:1};
const receipt:Receipt={schema_version:'communications.messages.v1',operation_id:'send-one',state:'accepted',revision:2,sequence:1};
describe('send reconciliation',()=>{
  it('reconciles a lost reply without another send',async()=>{
    let sends=0;const result=await reconcile(body,{send:async()=>{sends++;throw {status:503};},lookup:async operation=>{expect(operation).toBe(body.operation_id);return receipt;}});
    expect(result).toEqual(receipt);expect(sends).toBe(1);
  });
  it('retries identical bytes only once after an unrecorded result',async()=>{
    const attempts:Command[]=[];await expect(reconcile(body,{send:async value=>{attempts.push(value);throw {status:503};},lookup:async()=>({state:'pending'})})).rejects.toEqual({status:503});
    expect(attempts).toEqual([body,body]);expect(attempts[0]).toBe(attempts[1]);
  });
  it('never retries a definitive denial or stale revision',async()=>{
    for(const status of [403,409]){let lookups=0;await expect(reconcile(body,{send:async()=>{throw {status};},lookup:async()=>{lookups++;return receipt;}})).rejects.toEqual({status});expect(lookups).toBe(0);}
  });
  it('keeps uncertainty when lookup is unavailable',async()=>{
    let sends=0;await expect(reconcile(body,{send:async()=>{sends++;throw {status:503};},lookup:async()=>{throw {status:503};}})).rejects.toEqual({status:503});expect(sends).toBe(1);
  });
});

describe('unresolved command retention',()=>{
  it('keeps the original reference after a committed send loses its reply and a later revision denial',async()=>{
    const pending=new PendingCommand(body);
    const messages=new Map<string,Receipt>();
    const attempts:Command[]=[];
    let lookupAvailable=false;
    let sourceCurrent=true;
    const transport={
      send:async(value:Command)=>{
        attempts.push(value);
        if(!sourceCurrent) throw {status:409,code:'source_revision'};
        messages.set(value.operation_id,receipt);
        throw {status:503};
      },
      lookup:async(operation:string)=>{
        expect(operation).toBe(body.operation_id);
        if(!lookupAvailable) throw {status:503};
        return messages.get(operation) ?? {state:'pending' as const};
      }
    };
    await expect(pending.run(transport)).rejects.toEqual({status:503});
    expect(pending.uncertain).toBe(true);
    sourceCurrent=false;
    await expect(pending.run({...transport,lookup:async()=>({state:'pending'})})).rejects.toEqual({status:409,code:'source_revision'});
    expect(pending.uncertain).toBe(true);
    expect(pending.body).toBe(body);
    lookupAvailable=true;
    expect(await pending.run(transport)).toEqual(receipt);
    expect(attempts).toEqual([body,body]);
    expect(messages.size).toBe(1);
  });
  it('allows correction after an initial definitive denial',async()=>{
    const pending=new PendingCommand(body);
    await expect(pending.run({send:async()=>{throw {status:409};},lookup:async()=>({state:'pending'})})).rejects.toEqual({status:409});
    expect(pending.uncertain).toBe(false);
  });
});

describe('lost block confirmation',()=>{
  it('resolves the original reference through its receipt without another command',async()=>{
    const command:Command={...body,kind:'block',target:'seller',operation_id:'block-one'};
    const accepted:Receipt={...receipt,operation_id:command.operation_id};
    const pending=new PendingCommand(command);
    let sends=0;
    expect(await pending.run({send:async()=>{sends++;throw {status:503};},lookup:async operation=>{
      expect(operation).toBe(command.operation_id);return accepted;
    }})).toEqual(accepted);
    expect(sends).toBe(1);
    expect(pending.body).toBe(command);
  });
});
