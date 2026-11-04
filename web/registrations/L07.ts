import pricesEn from '../features/pricing/en.json';
import pricesAr from '../features/pricing/ar.json';
import '../features/pricing/styles.css';
const roles=['buyer','private_seller','dealer','brand','operator'] as const;
export default {
  lane:'L07',namespace:'buying-desk',
  routes:[{path:'/prices',roles:['public'],area:'account'}],
  navigation:[{id:'exact-prices',href:'/prices',label:{en:'Exact prices',ar:'الأسعار الدقيقة'},order:35,area:'storefront',roles:['public']}],
  dictionaries:{en:{...pricesEn},ar:{...pricesAr}},
  gateway:[
    {service:'pricing',path:'/v1/quotes',methods:['GET','POST'],roles:[...roles]},
    {service:'pricing',path:'/v1/quotes/:id',methods:['GET'],roles:[...roles]},
    {service:'pricing',path:'/v1/quotes/:id/review',methods:['POST'],roles:[...roles]},
  ],slots:[]
} satisfies import('../registry-types').Registration;
