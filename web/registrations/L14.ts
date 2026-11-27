import en from '../features/pricing/s2-en.json';
import ar from '../features/pricing/s2-ar.json';
import '../features/pricing/s2.css';
const roles=['buyer','private_seller','dealer','brand'] as const;
const gateway=(['offers','brand-quotes','repair-quotes'] as const).flatMap(name=>[
 {service:'pricing' as const,path:`/v1/${name}`,methods:['GET','POST'] as ('GET'|'POST')[],roles:[...roles]},
 {service:'pricing' as const,path:`/v1/${name}/:id`,methods:['GET'] as 'GET'[],roles:[...roles]},
 ...(name==='offers'?['answer','reconcile','block']:['accept','decline']).map(action=>({service:'pricing' as const,path:`/v1/${name}/:id/${action}`,methods:['POST'] as 'POST'[],roles:[...roles]})),
 ...(name==='offers'?[]:[{service:'pricing' as const,path:`/v1/${name}/context`,methods:['GET'] as 'GET'[],roles:['brand','dealer'] as ('brand'|'dealer')[]}]),
]);
export default {
 lane:'L14',namespace:'assessed-quotes',dictionaries:{en,ar},
 routes:[{path:'/offers',roles:[...roles],area:'account'},{path:'/brand-quotes',roles:['buyer','brand'],area:'account'},{path:'/repair-quotes',roles:['buyer','brand','dealer'],area:'account'}],
 navigation:[
  {id:'offers',href:'/offers',label:{en:'Offers',ar:'العروض'},order:42,area:'account',roles:[...roles]},
  {id:'brand-quotes',href:'/brand-quotes',label:{en:'Brand quotes',ar:'عروض العلامة'},order:43,area:'account',roles:['buyer','brand']},
  {id:'repair-quotes',href:'/repair-quotes',label:{en:'Repair quotes',ar:'عروض الإصلاح'},order:44,area:'account',roles:['buyer','brand','dealer']},
 ],gateway:[...gateway,{service:'pricing',path:'/v1/pricing-operations/:key',methods:['GET'],roles:[...roles]},
  {service:'pricing',path:'/v1/auction-quotes',methods:['POST'],roles:['buyer']},
  {service:'pricing',path:'/v1/auction-quotes/:id',methods:['GET'],roles:['buyer']},
  {service:'pricing',path:'/v1/auction-quotes/:id/review',methods:['POST'],roles:['buyer']}],
 slots:[{id:'l14-watch-offer',target:'watch.detail',load:()=>import('../features/offers/watch-slot')}],
} satisfies import('../registry-types').Registration;
