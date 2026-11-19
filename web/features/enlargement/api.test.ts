import { expect, it, vi } from 'vitest';
vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn().mockResolvedValue({revision:1})}));
import { authenticatedRequest } from '@/features/identity/session';
import { enlargementRead, endpoint, submit } from './api';
it('uses the identity-scoped boundary for private reads and stable commands',async()=>{
  const controller=new AbortController();
  await enlargementRead('request-1').ask(controller.signal);
  expect(authenticatedRequest).toHaveBeenCalledWith(`${endpoint}/requests/request-1`,{signal:controller.signal});
  const body={operation_id:'stable_operation',kind:'request'};
  await submit(body);
  expect(authenticatedRequest).toHaveBeenLastCalledWith(`${endpoint}/commands`,expect.objectContaining({method:'POST',body:JSON.stringify(body)}));
});
