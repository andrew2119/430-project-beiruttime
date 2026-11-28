import { accounts } from './accounts.mjs';
import { auditFeature } from './audit.mjs';
import { catalog } from './catalog.mjs';

export const features = [...accounts, auditFeature, ...catalog];
