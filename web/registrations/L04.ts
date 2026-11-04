import en from '../features/discovery/en.json';
import ar from '../features/discovery/ar.json';
import '../features/discovery/styles.css';
export default {
  lane:'L04',namespace:'discovery',
  routes:[{path:'/watches',roles:['public'],area:'storefront'},{path:'/watches/:id',roles:['public'],area:'storefront'},{path:'/search',roles:['public'],area:'storefront'}],
  navigation:[{id:'watches',href:'/watches',label:{en:'Watches',ar:'الساعات'},order:10,area:'storefront',roles:['public'],bottom:true},{id:'search',href:'/search',label:{en:'Search',ar:'البحث'},order:20,area:'storefront',roles:['public'],bottom:true}],
  dictionaries:{en,ar},
  gateway:[
    {service:'catalog',path:'/v1/listings/:id',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/discovery/watches',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/discovery/watches/:id',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/discovery/watches/:id/auction',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/listings/:listingId/photos/:assetId/:variant',methods:['GET'],roles:['public'],maxResponseBytes:8*1024*1024},
  ],
} satisfies import('../registry-types').Registration;
