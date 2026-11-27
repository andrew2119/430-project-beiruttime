import { expect,it } from 'vitest';
import registration from '../../../web/registrations/L14';
it('contributes three complete private tabs without replacing old routes',()=>{
 expect(registration.routes.map(route=>route.path)).toEqual(['/offers','/brand-quotes','/repair-quotes']);
 expect(registration.navigation.every(entry=>registration.routes.some(route=>route.path===entry.href))).toBe(true);
 expect(registration.routes.every(route=>!route.roles.includes('public' as never))).toBe(true);
 expect(registration.slots[0].target).toBe('watch.detail');
});
it('keeps exact English/Arabic key parity and only bounded Pricing gateway routes',()=>{
 expect(Object.keys(registration.dictionaries.en).sort()).toEqual(Object.keys(registration.dictionaries.ar).sort());
 expect(registration.gateway.every(route=>route.service==='pricing'&&!route.path.includes('*'))).toBe(true);
});
