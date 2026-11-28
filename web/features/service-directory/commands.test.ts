import { beforeEach, expect, it, vi } from 'vitest';
const memory=vi.hoisted(()=>({slots:[] as unknown[],cursor:0,send:vi.fn(),effects:[] as (()=>void)[]}));
vi.mock('react',()=>({
  useRef:(value:unknown)=>{const index=memory.cursor++;return memory.slots[index]??(memory.slots[index]={current:value});},
  useState:(value:unknown)=>{const index=memory.cursor++;if(!(index in memory.slots))memory.slots[index]=value;return [memory.slots[index],(next:unknown)=>{memory.slots[index]=next;}];},
  useEffect:(effect:()=>()=>void)=>{const index=memory.cursor++;if(!(index in memory.slots)){memory.slots[index]=true;memory.effects.push(effect());}},
}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:memory.send}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:'synthetic-access'})}));
import { useCommandMutation, useJsonCommand } from './api';
import { ApiError } from '@/lib/api/client';
function render<T>(factory:()=>T){memory.cursor=0;return factory();}
beforeEach(()=>{memory.effects.forEach(cleanup=>cleanup());memory.effects=[];memory.slots=[];memory.cursor=0;memory.send.mockReset();vi.stubGlobal('window',new EventTarget());});
it('keeps the original reference/body after a lost response and refuses a conflicting action',async()=>{
  const command=render(useJsonCommand);
  memory.send.mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValue({revision:1});
  await expect(command('/api/choice',{revision:0})).rejects.toThrow();
  await expect(command('/api/choice',{revision:1})).rejects.toMatchObject({code:'pending_operation'});
  await command('/api/choice',{revision:0});
  expect(memory.send).toHaveBeenCalledTimes(2);
  expect(memory.send.mock.calls[0][1].headers['Idempotency-Key']).toBe(memory.send.mock.calls[1][1].headers['Idempotency-Key']);
  expect(memory.send.mock.calls[0][1].body).toBe(memory.send.mock.calls[1][1].body);
});
it('retries the captured operation after an uncertain result even if the current form changes',async()=>{
  const original=vi.fn().mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValue({revision:1});
  render(()=>useCommandMutation({mutationFn:original})).mutate();
  await vi.waitFor(()=>expect(render(()=>useCommandMutation({mutationFn:original})).isError).toBe(true));
  const changed=vi.fn();
  render(()=>useCommandMutation({mutationFn:changed})).mutate();
  await vi.waitFor(()=>expect(render(()=>useCommandMutation({mutationFn:changed})).isSuccess).toBe(true));
  expect(original).toHaveBeenCalledTimes(2);expect(changed).not.toHaveBeenCalled();
});
it('allows corrected local validation without retaining an invalid action',async()=>{
  const invalid=vi.fn().mockRejectedValue(new RangeError('Invalid dollar amount'));
  render(()=>useCommandMutation({mutationFn:invalid})).mutate();
  await vi.waitFor(()=>expect(render(()=>useCommandMutation({mutationFn:invalid})).isError).toBe(true));
  const corrected=vi.fn().mockResolvedValue({revision:1});
  render(()=>useCommandMutation({mutationFn:corrected})).mutate();
  await vi.waitFor(()=>expect(render(()=>useCommandMutation({mutationFn:corrected})).isSuccess).toBe(true));
  expect(invalid).toHaveBeenCalledTimes(1);expect(corrected).toHaveBeenCalledTimes(1);
});
it('aborts and clears the private attempt when access changes',async()=>{
  memory.send.mockResolvedValue({revision:1});
  const command=render(useJsonCommand);
  await command('/api/choice',{revision:0});
  window.dispatchEvent(new Event('bt:access-change'));
  await command('/api/choice',{revision:0});
  expect(memory.send.mock.calls[0][1].headers['Idempotency-Key']).not.toBe(memory.send.mock.calls[1][1].headers['Idempotency-Key']);
});
