import { expect, it, vi } from 'vitest';
import { PendingOperation } from './pending';

it('retains the exact payload after a lost response until the same action resolves', async()=>{
  const pending=new PendingOperation();
  const body={operation_id:'stable_operation',expected_revision:3,payload:{part_ids:['link']}};
  const send=vi.fn().mockRejectedValueOnce(new Error('lost_response')).mockResolvedValue({revision:4});
  await expect(pending.run(body,send)).rejects.toThrow('lost_response');
  expect(pending.body).toBe(body);
  await expect(pending.run({...body,operation_id:'replacement'},send)).rejects.toThrow('operation_pending');
  expect(send).toHaveBeenCalledTimes(1);
  expect(await pending.run(pending.body!,send)).toEqual({revision:4});
  expect(send.mock.calls[0][0]).toBe(send.mock.calls[1][0]);
  expect(pending.body).toBeNull();
});

it('admits only one concurrent retry and clears only after resolution', async()=>{
  const pending=new PendingOperation();
  const body={operation_id:'stable_operation'};
  let resolve!:(value:number)=>void;
  const send=vi.fn(()=>new Promise<number>(done=>{resolve=done;}));
  const first=pending.run(body,send);
  expect(await pending.run(body,send)).toBeNull();
  expect(send).toHaveBeenCalledTimes(1);
  expect(pending.body).toBe(body);
  resolve(4);
  expect(await first).toBe(4);
  expect(pending.body).toBeNull();
});
