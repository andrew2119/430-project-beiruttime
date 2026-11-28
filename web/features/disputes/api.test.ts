import { describe, expect, it, vi } from 'vitest';
import type { Command } from '@contracts/contracts-trust/disputes/v1';
vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn()}));
import { authenticatedRequest } from '@/features/identity/session';
import { send } from './api';

describe('immutable submission recovery',()=>{
 it('resends a subsequent response after a request is lost before receipt',async()=>{
  const transport=vi.mocked(authenticatedRequest);
  const controller=new AbortController();
  const body:Command={schema_version:'disputes.v1',operation_id:'response_second',subject_id:'order_1',organization_id:null,expected_revision:3,source_revision:1,assignment_revision:1,kind:'respond',reason:'Additional recorded response',evidence:[],amount_minor:0};
  transport.mockResolvedValueOnce({operation_id:'response_first',state:'responded'});
  await send('scope',{...body,operation_id:'response_first',expected_revision:2},controller.signal);
  transport.mockRejectedValueOnce(new TypeError('Connection unavailable'));
  await expect(send('scope',body,controller.signal)).rejects.toThrow('Connection unavailable');
  transport.mockResolvedValueOnce({operation_id:body.operation_id,state:'responded'});
  await expect(send('scope',body,controller.signal)).resolves.toMatchObject({operation_id:body.operation_id,state:'responded'});
  expect(transport.mock.calls[1]).toEqual(transport.mock.calls[2]);
  expect(transport.mock.calls[2][0]).toMatch(/\/commands$/);
  expect(transport.mock.calls[2][1]).toMatchObject({method:'POST',body:JSON.stringify(body)});
 });
});
