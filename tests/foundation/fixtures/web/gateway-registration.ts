import foundation from './foundation-original';
import type { Registration } from '../registry-types';
// Synthetic transport only: no authentication operation or production endpoint is implemented here.
export default {
  ...foundation,
  gateway: [{ service: 'identity', path: '/v1/foundation-origin-proof', methods: ['POST'], roles: ['public'] }],
} satisfies Registration;
