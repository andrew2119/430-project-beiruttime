import { describe, it, expect } from 'vitest';
import { PendingOperation } from '../../../../web/features/browser-push/pending';
import { initializeDevice } from '../../../../web/features/browser-push/initialization';
import { copy } from '../../../../web/features/browser-push/copy';
import type { PushCommand, PushResult } from '../../../../packages/contracts-comms/browser-push';
const command:PushCommand={schema_version:'browser-push.v1',operation_id:'20000000-0000-4000-8000-000000000001',device_id:'10000000-0000-4000-8000-000000000001',expected_revision:0,action:'revoke',permission:'default',subscription:null};
const result:PushResult={schema_version:'browser-push.v1',operation_id:command.operation_id,device_id:command.device_id,state:'revoked',revision:1};
describe('retained device operation',()=>{
  it('retries exact bytes after a lost response across language reads',async()=>{
    const sent:PushCommand[]=[];
    const operation=new PendingOperation(async body=>{sent.push(body);if(sent.length===1)throw Error('timeout');return result;});
    await expect(operation.run(command)).rejects.toThrow('timeout');
    expect(copy.ar.pending).toBeTruthy();expect(copy.en.pending).toBeTruthy();
    expect(await operation.run({...command})).toEqual(result);
    expect(sent).toEqual([command,command]);
  });
  it('deduplicates concurrent presses',async()=>{
    let finish!:(value:PushResult)=>void,calls=0;
    const operation=new PendingOperation(()=>{calls++;return new Promise(resolve=>{finish=resolve;});});
    const one=operation.run(command),two=operation.run(command);
    expect(one).toBe(two);expect(calls).toBe(1);finish(result);await one;
  });
  it('rejects replacing an uncertain operation',async()=>{
    const operation=new PendingOperation(async()=>{throw Error('timeout');});
    await expect(operation.run(command)).rejects.toThrow();
    await expect(operation.run({...command,operation_id:'another'})).rejects.toThrow('pending');
  });
  it('isolates the retained request from transport mutation',async()=>{
    let calls=0;
    const operation=new PendingOperation(async body=>{calls++;expect(body.expected_revision).toBe(0);body.expected_revision=99;if(calls===1)throw Error('timeout');return result;});
    await expect(operation.run(command)).rejects.toThrow();await operation.run(command);
    expect(command.expected_revision).toBe(0);
  });
  it('provides both languages for every recovery action',()=>{
    expect(Object.keys(copy.ar).sort()).toEqual(Object.keys(copy.en).sort());
    for(const value of Object.values(copy.ar))expect(value).toMatch(/[\u0600-\u06ff]/);
  });
});

describe('device initialization recovery',()=>{
  it('reports unavailable on denied storage and retries the installation read',()=>{
    let blocked=true,calls=0;
    const read=()=>{calls++;if(blocked)throw new Error('unavailable');return command.device_id;};
    expect(initializeDevice(read)).toEqual({device:null,state:'unavailable'});
    blocked=false;
    expect(initializeDevice(read)).toEqual({device:command.device_id,state:'ready'});
    expect(calls).toBe(2);
  });
  it('keeps repeated initialization failures unavailable',()=>{
    const read=()=>{throw new Error('unavailable');};
    expect(initializeDevice(read).state).toBe('unavailable');
    expect(initializeDevice(read).state).toBe('unavailable');
  });
});
