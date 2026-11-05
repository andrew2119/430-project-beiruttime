import en from '../features/auction-policy/en.json';
import ar from '../features/auction-policy/ar.json';
import '../features/auction-policy/styles.css';
export default {
  lane:'L12',namespace:'auction-policy',
  routes:[{path:'/auction-policy',roles:['public'],area:'storefront'}],
  navigation:[{id:'auction-policy',href:'/auction-policy',label:{en:'Auction policy',ar:'سياسة المزاد'},order:46,area:'storefront',roles:['public']}],
  dictionaries:{en,ar},
  gateway:[
    {service:'auction',path:'/v2/auctions',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v2/auctions/:id',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions/:id/policy',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions/:id/policy',methods:['PATCH'],roles:['private_seller','dealer','brand']}
  ]
} satisfies import('../registry-types').Registration;
