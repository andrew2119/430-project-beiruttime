import en from '../features/auction-management/en.json';
import ar from '../features/auction-management/ar.json';
import '../features/auction-management/styles.css';
export default {
  lane:'L05',namespace:'auction-management',
  routes:[{path:'/seller/auctions',roles:['private_seller','dealer','brand'],area:'seller'}],
  navigation:[{id:'seller-auctions',href:'/seller/auctions',label:{en:'Auctions',ar:'المزادات'},order:45,area:'seller',roles:['private_seller','dealer','brand']}],
  dictionaries:{en,ar},
  gateway:[
    {service:'auction',path:'/v1/auctions',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions',methods:['POST'],roles:['private_seller','dealer','brand']},
    {service:'auction',path:'/v1/seller/auctions',methods:['GET'],roles:['private_seller','dealer','brand']},
    {service:'auction',path:'/v1/auctions/:id',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions/:id/timing',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auction-timing',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions/:id/rules',methods:['PATCH'],roles:['private_seller','dealer','brand']},
    {service:'auction',path:'/v1/auctions/:id/history',methods:['GET'],roles:['public']},
    {service:'auction',path:'/v1/auctions/:id/bids',methods:['POST'],roles:['buyer']},
    {service:'auction',path:'/v1/auctions/:id/operations/:operation',methods:['GET'],roles:['buyer','private_seller','dealer','brand']},
    {service:'auction',path:'/v1/auction-operations/by-key/:key',methods:['GET'],roles:['buyer','private_seller','dealer','brand']},
    {service:'auction',path:'/v1/my-bids',methods:['GET'],roles:['buyer']},
    {service:'pricing',path:'/v1/quotes',methods:['POST'],roles:['buyer']},
    {service:'pricing',path:'/v1/quotes/:id',methods:['GET'],roles:['buyer']},
    {service:'pricing',path:'/v1/quotes/:id/review',methods:['POST'],roles:['buyer']},
    {service:'communications',path:'/v1/bid-notices',methods:['GET'],roles:['buyer']},
    {service:'communications',path:'/v1/bid-notices/:id',methods:['GET'],roles:['buyer']}
  ],
  slots:[
    {id:'manual-bid',target:'watch.detail',load:()=>import('../features/auction-management/bid-slot')},
    {id:'bid-notices',target:'buyer.dashboard',load:()=>import('../features/auction-management/notices-slot')}
  ]
} satisfies import('../registry-types').Registration;
