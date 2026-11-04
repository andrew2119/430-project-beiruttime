export { navigation, registeredRoutes, featureMessages, slotsFor } from '../../../../web/registry-loader';
import { gatewayRegistrations as production } from '../../../../web/registry-loader';
import type { Registration } from '../../../../web/registry-types';
// Frozen L01 gateway contract only; authentication still runs in the real Identity service.
const identity: NonNullable<Registration['gateway']> = ['register','login','refresh','logout'].map(operation=>({service:'identity',path:'/v1/accounts/'+operation,methods:['POST'],roles:['public'],forwardCookies:['bt_refresh']}));
export const gatewayRegistrations=[...production,...identity];
