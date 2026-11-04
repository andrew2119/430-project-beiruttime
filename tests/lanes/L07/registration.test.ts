import { expect, test } from '../../../web/node_modules/vitest/dist/index.js';
import registration from '../../../web/registrations/L07';
import { validateRegistrations } from '../../../web/registry-loader';
test('owned registration has safe locale namespace, matched dictionaries and scoped gateway endpoints',()=>{
  expect(()=>validateRegistrations([registration])).not.toThrow();
  expect(Object.keys(registration.dictionaries.en).sort()).toEqual(Object.keys(registration.dictionaries.ar).sort());
  expect(registration.routes.map(route=>route.path)).toEqual(['/prices','/inbox','/buying']);
  expect(registration.gateway.every(endpoint=>endpoint.path.startsWith('/v1/')&&!endpoint.roles.includes('public' as never))).toBe(true);
});
