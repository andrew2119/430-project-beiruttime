import en from '../features/proxy-bid/en.json';
import ar from '../features/proxy-bid/ar.json';
import '../features/proxy-bid/styles.css';
export default {
  lane:'L06',namespace:'buyer-workspace',
  routes:[{path:'/buyer',roles:['buyer'],area:'account'},{path:'/buyer/auctions/:listingId',roles:['buyer'],area:'account'}],
  navigation:[{id:'buyer-workspace',href:'/buyer',label:{en:'My buying',ar:'مشترياتي'},order:40,area:'account',roles:['buyer'],bottom:true}],
  dictionaries:{en,ar},
  gateway:[
    {service:'communications',path:'/v1/buyer-workspace',methods:['GET'],roles:['buyer']},
    {service:'auction',path:'/v1/auctions/:id/maximum',methods:['POST'],roles:['buyer']},
  ],
  slots:[{id:'L06.private-maximum',target:'watch.detail',load:()=>import('../features/proxy-bid/proxy-bid')}],
} satisfies import('../registry-types').Registration;
