import { fileURLToPath } from 'node:url';
import profileConfig from '../../../../web/features/seller-profile/vitest.config';

const config = {
 ...profileConfig,
 root:fileURLToPath(new URL('../../../../web/',import.meta.url)),
};

export default config;
