import type { Registration } from '../registry-types';

// Existing public entries remain with their declaring lane.
export default {
  lane: 'L18',
  namespace: 'trust-runtime',
  routes: [],
  navigation: [],
  dictionaries: { en: {}, ar: {} },
  gateway: [],
  slots: [],
} satisfies Registration;
