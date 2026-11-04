import en from '../features/service-directory/en.json';
import ar from '../features/service-directory/ar.json';
import movementEn from '../features/movement-option/en.json';
import movementAr from '../features/movement-option/ar.json';
import '../features/service-directory/styles.css';
import '../features/movement-option/styles.css';
export default {
  lane:'L11',namespace:'service-directory',
  routes:[{path:'/services',roles:['public'],area:'storefront'}],
  navigation:[{id:'official-services',href:'/services',label:{en:'Official care',ar:'العناية الرسمية'},order:40,area:'storefront',roles:['public'],bottom:true}],
  dictionaries:{en:{...en,...Object.fromEntries(Object.entries(movementEn).map(([key,value])=>['movement_'+key,value]))},ar:{...ar,...Object.fromEntries(Object.entries(movementAr).map(([key,value])=>['movement_'+key,value]))}},
  gateway:[
    // These are the frozen Identity session APIs consumed by care screens, not alternate auth handlers.
    {service:'identity',path:'/v1/accounts/register',methods:['POST'],roles:['public'],forwardCookies:['bt_refresh'],maxBodyBytes:8192},
    {service:'identity',path:'/v1/accounts/login',methods:['POST'],roles:['public'],forwardCookies:['bt_refresh'],maxBodyBytes:8192},
    {service:'identity',path:'/v1/accounts/refresh',methods:['POST'],roles:['public'],forwardCookies:['bt_refresh'],maxBodyBytes:8192},
    {service:'identity',path:'/v1/accounts/logout',methods:['POST'],roles:['public'],forwardCookies:['bt_refresh'],maxBodyBytes:8192},
    {service:'service-operations',path:'/v1/directory/businesses',methods:['GET'],roles:['public']},
    {service:'service-operations',path:'/v1/directory/businesses/:id',methods:['GET'],roles:['public']},
    {service:'service-operations',path:'/v1/directory/providers/:id',methods:['GET'],roles:['public']},
    {service:'service-operations',path:'/v1/directory/businesses/:id',methods:['PUT'],roles:['brand','dealer']},
    {service:'service-operations',path:'/v1/directory/choices/current',methods:['GET'],roles:['buyer']},
    {service:'service-operations',path:'/v1/directory/choices',methods:['POST'],roles:['buyer']},
    {service:'catalog',path:'/v1/options/movement',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/options/movement/:id',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/options/movement/:id',methods:['PUT'],roles:['brand']},
    {service:'catalog',path:'/v1/options/movement/selections/current',methods:['GET'],roles:['buyer']},
    {service:'catalog',path:'/v1/options/movement/selections',methods:['POST'],roles:['buyer']}
  ],slots:[]
} satisfies import('../registry-types').Registration;
