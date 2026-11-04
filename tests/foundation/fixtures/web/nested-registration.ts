import foundation from './foundation-original';
import type { Registration } from '../registry-types';
// Installed only inside the isolated production-proof build, never a domain registration.
export default {
  ...foundation,
  routes: [...foundation.routes,
    { path: '/operations/moderation', roles: ['public'], area: 'operator' },
    { path: '/seller/dashboard', roles: ['public'], area: 'seller' },
  ],
} satisfies Registration;
