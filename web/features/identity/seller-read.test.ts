import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createReadScope } from '@/lib/page-speed/scope';
import { optionsFor } from '@/lib/page-speed/definition';
import { sellerApplicationRead } from './reads';
import SellerView from './seller-view';
import { ApiError } from '@/lib/api/client';

const context = vi.hoisted(()=>({invoke:vi.fn(),locale:'en' as 'en'|'ar',fingerprint:'test-access'}));
let scope: ReturnType<typeof createReadScope>;
vi.mock('@/lib/page-speed/provider',()=>({usePageReadScope:()=>scope}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>context.locale}));
vi.mock('next/link',()=>({default:'a'}));
vi.mock('./session',()=>({useSession:()=>({access_fingerprint:context.fingerprint}),authenticatedRequest:context.invoke}));
function render() {
  return renderToStaticMarkup(createElement(QueryClientProvider,{client:scope.client},createElement(SellerView)));
}
beforeEach(()=>{scope=createReadScope('test-access');context.invoke.mockReset();context.locale='en';context.fingerprint='test-access';});
afterEach(()=>scope.clear());
it('retains the same private answer across visits and language changes without another loading frame',async()=>{
  context.invoke.mockResolvedValue({application:null});
  const read=sellerApplicationRead(context.fingerprint);
  expect(read.key).toEqual(['private-seller','test-access']);
  expect(read.warm).toBe('open-only');
  await scope.client.fetchQuery(optionsFor(scope,read));
  expect(render()).toContain('You have not submitted');
  context.locale='ar';
  expect(render()).toContain('لم ترسل');
  context.locale='en';
  expect(render()).toContain('You have not submitted');
  expect(render()).not.toContain('aria-busy="true"');
  expect(context.invoke).toHaveBeenCalledTimes(1);
});
it('keeps an answer during unavailable refresh but hides it after current permission denial',async()=>{
  const read=sellerApplicationRead(context.fingerprint);
  context.invoke.mockResolvedValueOnce({application:null});
  await scope.client.fetchQuery(optionsFor(scope,read));
  context.invoke.mockRejectedValueOnce(new ApiError(503,'unavailable',''));
  await expect(scope.client.fetchQuery({...optionsFor(scope,read),staleTime:0})).rejects.toThrow();
  expect(render()).toContain('You have not submitted');
  context.invoke.mockRejectedValueOnce(new ApiError(403,'forbidden',''));
  await expect(scope.client.fetchQuery({...optionsFor(scope,read),staleTime:0})).rejects.toThrow();
  expect(render()).not.toContain('You have not submitted');
  expect(render()).not.toContain('name="identity_name"');
});
it('does not reuse a private answer after the access scope changes',async()=>{
  context.invoke.mockResolvedValueOnce({application:null});
  await scope.client.fetchQuery(optionsFor(scope,sellerApplicationRead(context.fingerprint)));
  scope.clear();scope=createReadScope('test-other-access');context.fingerprint='test-other-access';
  expect(render()).toContain('aria-busy="true"');
  expect(render()).not.toContain('You have not submitted');
});
