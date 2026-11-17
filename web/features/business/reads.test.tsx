import { beforeEach, expect, it, vi } from 'vitest';
import { createReadScope } from '@/lib/page-speed/scope';
import { optionsFor, warmPageRead } from '@/lib/page-speed/definition';
const request = vi.hoisted(() => vi.fn());
vi.mock('./transport', () => ({ businessRequest: request }));
import { businessRouteReads, directoryRead, contactsRead, businessRead } from './reads';
import declarations from './delivery-contract.json';
beforeEach(() => request.mockReset());
it('shares warmed answers with mounted reads and later visits', async () => {
  const scope = createReadScope('test-public');
  const answer = {items: [], total: 0, page: 1, page_size: 25};
  request.mockResolvedValue(answer);
  await warmPageRead(scope, businessRouteReads['/business']());
  expect(await scope.client.fetchQuery(optionsFor(scope, directoryRead(1)))).toEqual(answer);
  expect(await scope.client.fetchQuery(optionsFor(scope, directoryRead(1)))).toEqual(answer);
  expect(request).toHaveBeenCalledTimes(1);
  scope.clear();
});
it('never warms private reads and clears answers on revoked access', async () => {
  const scope = createReadScope('test-member');
  await warmPageRead(scope, contactsRead('test-access'));
  expect(request).not.toHaveBeenCalled();
  request.mockResolvedValue({email: 'test@example.invalid'});
  await scope.client.fetchQuery(optionsFor(scope, contactsRead('test-access')));
  scope.clear();
  expect(scope.client.getQueryCache().getAll()).toHaveLength(0);
  await expect(optionsFor(scope, contactsRead('test-access')).queryFn({signal:new AbortController().signal})).rejects.toThrow();
  expect(request).toHaveBeenCalledTimes(1);
});
it('separates revisions and rejects late revoked answers', async () => {
  const scope = createReadScope('test-private');
  let finish!: (answer: string) => void;
  const read = businessRead(['proof','test-watch',2], () => new Promise<string>(resolve => {finish=resolve;}));
  expect(read.key).not.toEqual(businessRead(['proof','test-watch',3], async () => '').key);
  const pending = optionsFor(scope, read).queryFn({signal:new AbortController().signal});
  scope.clear(); finish('private');
  await expect(pending).rejects.toThrow('Page access changed');
});
it('declares every feature route with unmeasured read contracts', () => {
  expect(declarations.map(page => page.route).sort()).toEqual(Object.keys(businessRouteReads).sort());
  for (const page of declarations) {
    expect(Object.keys(page).sort()).toEqual(['route','file','view','kind','reason','content','read','proof'].sort());
    expect(page).toMatchObject({kind:'reads',proof:'owed'});
    expect(page.view).toMatch(/^web\/features\/business\//);
  }
});
