import en from '../features/withdrawal/en.json';
import ar from '../features/withdrawal/ar.json';
import paymentEn from '../features/payments/en.json';
import paymentAr from '../features/payments/ar.json';
import {connectedCopy} from '../features/buy-now/connected-copy';
import '../features/withdrawal/styles.css';
import '../features/payments/styles.css';
const sellers=['private_seller','dealer','brand'] as const;
export default {
  lane:'L13',namespace:'winner-withdrawal-payment',
  routes:[{path:'/seller/withdrawals',roles:[...sellers],area:'seller'}],
  navigation:[{id:'l13-withdrawals',href:'/seller/withdrawals',label:{en:'Withdrawals',ar:'سحب الإعلانات'},roles:[...sellers],area:'seller',order:44}],
  dictionaries:{en:{...en,...Object.fromEntries(Object.entries(paymentEn).map(([k,v])=>['payment_'+k,v])),...Object.fromEntries(Object.entries(connectedCopy.en).map(([k,v])=>['checkout_'+k,v]))},ar:{...ar,...Object.fromEntries(Object.entries(paymentAr).map(([k,v])=>['payment_'+k,v])),...Object.fromEntries(Object.entries(connectedCopy.ar).map(([k,v])=>['checkout_'+k,v]))}},
  gateway:[
    {service:'orders',path:'/v1/checkout-context',methods:['GET'],roles:['buyer']},
    {service:'orders',path:'/v1/exact-reservations',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id/checkout',methods:['GET'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id/payment-attempts',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/payment-attempts/:id/simulate',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id/journal',methods:['GET'],roles:['buyer',...sellers]},
    {service:'catalog',path:'/v1/me/withdrawals',methods:['GET'],roles:[...sellers]},
    {service:'catalog',path:'/v1/listings/:id/withdrawals',methods:['POST'],roles:[...sellers]},
    {service:'catalog',path:'/v1/listings/:id/withdrawals/current',methods:['GET'],roles:[...sellers]},
    {service:'auction',path:'/v1/auctions/:id/result',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions/:id/my-result',methods:['GET'],roles:['buyer']},
  ],
  slots:[{id:'l13-auction-winner',target:'watch.detail',load:()=>import('../features/buy-now/winner-slot')}]
} satisfies import('../registry-types').Registration;
