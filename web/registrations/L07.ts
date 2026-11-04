import pricesEn from '../features/pricing/en.json';
import pricesAr from '../features/pricing/ar.json';
import inboxEn from '../features/inbox/en.json';
import inboxAr from '../features/inbox/ar.json';
import '../features/pricing/styles.css';
import '../features/inbox/styles.css';
const roles=['buyer','private_seller','dealer','brand','operator'] as const;
export default {
  lane:'L07',namespace:'buying-desk',
  routes:[{path:'/prices',roles:['public'],area:'account'},{path:'/inbox',roles:['buyer'],area:'account'},{path:'/buying',roles:['buyer'],area:'account'}],
  navigation:[{id:'exact-prices',href:'/prices',label:{en:'Exact prices',ar:'الأسعار الدقيقة'},order:35,area:'storefront',roles:['public']},{id:'private-inbox',href:'/inbox',label:{en:'Inbox',ar:'الصندوق'},order:30,area:'account',roles:['buyer'],bottom:true},{id:'buying-readiness',href:'/buying',label:{en:'Buying readiness',ar:'جاهزية الشراء'},order:40,area:'account',roles:['buyer']}],
  dictionaries:{en:{...pricesEn,...inboxEn},ar:{...pricesAr,...inboxAr}},
  gateway:[
    {service:'pricing',path:'/v1/quotes',methods:['GET','POST'],roles:[...roles]},
    {service:'pricing',path:'/v1/quotes/:id',methods:['GET'],roles:[...roles]},
    {service:'pricing',path:'/v1/quotes/:id/review',methods:['POST'],roles:[...roles]},
    {service:'communications',path:'/v1/inbox',methods:['GET'],roles:[...roles]},
    {service:'communications',path:'/v1/inbox/preferences',methods:['GET','PUT'],roles:[...roles]},
    {service:'communications',path:'/v1/inbox/:id/read',methods:['POST'],roles:[...roles]},
    {service:'communications',path:'/v1/inbox/:id/clear',methods:['POST'],roles:[...roles]},
    {service:'communications',path:'/v1/inbox/:id/destination',methods:['GET'],roles:[...roles]},
    {service:'communications',path:'/v1/buying/readiness',methods:['GET'],roles:[...roles]},
    {service:'communications',path:'/v1/buying/drafts',methods:['GET','POST'],roles:[...roles]},
    {service:'communications',path:'/v1/buying/drafts/:id',methods:['GET','PUT'],roles:[...roles]},
    {service:'communications',path:'/v1/buying/drafts/:id/send',methods:['POST'],roles:[...roles]},
    {service:'communications',path:'/v1/buying/drafts/:id/accept',methods:['POST'],roles:[...roles]},
    {service:'communications',path:'/v1/buying/payment',methods:['POST'],roles:[...roles]}
  ],slots:[]
} satisfies import('../registry-types').Registration;
