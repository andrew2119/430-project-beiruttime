import checkoutEn from '../features/buy-now/en.json';
import checkoutAr from '../features/buy-now/ar.json';
import draftEn from '../features/request-drafts/en.json';
import draftAr from '../features/request-drafts/ar.json';
import '../features/buy-now/styles.css';
import '../features/request-drafts/styles.css';
const privateRoles=['buyer','private_seller','dealer','brand','operator'] as const;
export default {
  lane:'L08',namespace:'purchase-requests',
  routes:[{path:'/checkout',roles:[...privateRoles],area:'account'},{path:'/checkout/:id',roles:[...privateRoles],area:'account'},{path:'/custom-requests',roles:['buyer'],area:'account'}],
  navigation:[{id:'l08-checkout',href:'/checkout',label:{en:'Reservations',ar:'الحجوزات'},order:45,area:'account',roles:[...privateRoles]},{id:'l08-requests',href:'/custom-requests',label:{en:'Private requests',ar:'الطلبات الخاصة'},order:46,area:'account',roles:['buyer']}],
  dictionaries:{en:{...Object.fromEntries(Object.entries(checkoutEn).map(([k,v])=>['checkout_'+k,v])),...Object.fromEntries(Object.entries(draftEn).map(([k,v])=>['draft_'+k,v]))},ar:{...Object.fromEntries(Object.entries(checkoutAr).map(([k,v])=>['checkout_'+k,v])),...Object.fromEntries(Object.entries(draftAr).map(([k,v])=>['draft_'+k,v]))}},
  gateway:[
    {service:'orders',path:'/v1/watches/:id/availability',methods:['GET'],roles:['public']},
    {service:'orders',path:'/v1/listings/:id/availability',methods:['GET'],roles:['public']},
    {service:'orders',path:'/v1/reservations',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/operations/:id',methods:['GET'],roles:[...privateRoles]},
    {service:'orders',path:'/v1/orders',methods:['GET'],roles:[...privateRoles]},
    {service:'orders',path:'/v1/me/reservations',methods:['GET'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id',methods:['GET'],roles:[...privateRoles]},
    {service:'orders',path:'/v1/orders/:id/transitions',methods:['POST'],roles:['operator','dealer','brand']},
    {service:'orders',path:'/v1/orders/:id/intake',methods:['GET','POST'],roles:['operator','dealer','brand']},
    {service:'catalog',path:'/v1/request-drafts',methods:['GET','POST'],roles:['buyer']},
    {service:'catalog',path:'/v1/request-drafts/:id',methods:['GET','PATCH'],roles:['buyer']},
    {service:'catalog',path:'/v1/request-drafts/:id/readiness',methods:['GET'],roles:['buyer']},
    {service:'catalog',path:'/v1/request-drafts/:id/actions/:action',methods:['POST'],roles:['buyer']},
    {service:'catalog',path:'/v1/request-draft-operations/:id',methods:['GET'],roles:['buyer']},
    {service:'catalog',path:'/v1/request-draft-catalogue',methods:['GET'],roles:['buyer']},
    {service:'catalog',path:'/v1/request-draft-configurations/:id',methods:['GET'],roles:['buyer']}
  ],
  slots:[{id:'l08-buy-now',target:'watch.detail',load:()=>import('../features/buy-now/watch-slot')}]
} satisfies import('../registry-types').Registration;
