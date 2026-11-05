import paymentEn from '../features/payments/en.json';
import paymentAr from '../features/payments/ar.json';
import {connectedCopy} from '../features/buy-now/connected-copy';
import '../features/payments/styles.css';
const sellers=['private_seller','dealer','brand'] as const;
export default {
  lane:'L13',namespace:'winner-withdrawal-payment',
  routes:[],
  navigation:[],
  dictionaries:{en:{...Object.fromEntries(Object.entries(paymentEn).map(([k,v])=>['payment_'+k,v])),...Object.fromEntries(Object.entries(connectedCopy.en).map(([k,v])=>['checkout_'+k,v]))},ar:{...Object.fromEntries(Object.entries(paymentAr).map(([k,v])=>['payment_'+k,v])),...Object.fromEntries(Object.entries(connectedCopy.ar).map(([k,v])=>['checkout_'+k,v]))}},
  gateway:[
    {service:'orders',path:'/v1/checkout-context',methods:['GET'],roles:['buyer']},
    {service:'orders',path:'/v1/exact-reservations',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id/checkout',methods:['GET'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id/payment-attempts',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/payment-attempts/:id/simulate',methods:['POST'],roles:['buyer']},
    {service:'orders',path:'/v1/orders/:id/journal',methods:['GET'],roles:['buyer',...sellers]},
  ],
  slots:[]
} satisfies import('../registry-types').Registration;
