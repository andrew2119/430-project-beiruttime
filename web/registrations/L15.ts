import en from '../features/brand-decisions/en.json';
import ar from '../features/brand-decisions/ar.json';
import '../features/brand-decisions/styles.css';
const sellers=['buyer','private_seller','dealer','brand'] as const;
const participants=['buyer','brand'] as const;
// Additive browser aliases preserve the frozen version-one gateway boundary.
export default {
 lane:'L15',namespace:'brand-decisions',
 routes:[{path:'/business/customizations',roles:['brand'],area:'seller'}],
 navigation:[{id:'brand-customizations',href:'/business/customizations',label:{en:'Customization decisions',ar:'قرارات التخصيص'},roles:['brand'],area:'seller',order:65}],
 dictionaries:{en,ar},
 gateway:[
  {service:'catalog',path:'/v1/seller/listings/:id/revisions',methods:['GET','POST'],roles:[...sellers]},
  {service:'catalog',path:'/v1/seller/listing-edit-operations/:id',methods:['GET'],roles:[...sellers]},
  {service:'catalog',path:'/v1/seller/listing-edit-operations/:id/resume',methods:['POST'],roles:[...sellers]},
  {service:'catalog',path:'/v1/configurations/:id/validate',methods:['POST'],roles:['buyer']},
  {service:'catalog',path:'/v1/brands/:id/compatibility',methods:['GET'],roles:['public']},
  {service:'catalog',path:'/v1/brands/:id/compatibility/:rule',methods:['PUT'],roles:['brand']},
  {service:'catalog',path:'/v1/request-drafts/:id/submit',methods:['POST'],roles:['buyer']},
  {service:'catalog',path:'/v1/customization-requests',methods:['GET'],roles:[...participants]},
  {service:'catalog',path:'/v1/customization-requests/:id',methods:['GET'],roles:[...participants]},
  {service:'catalog',path:'/v1/customization-requests/:id/revisions',methods:['GET'],roles:[...participants]},
  {service:'catalog',path:'/v1/customization-requests/:id/references/:reference',methods:['GET'],roles:[...participants],maxResponseBytes:1100000},
  {service:'catalog',path:'/v1/customization-operations/:id',methods:['GET'],roles:[...participants]},
  {service:'catalog',path:'/v1/customization-requests/:id/decisions',methods:['POST'],roles:['brand']},
  {service:'catalog',path:'/v1/customization-requests/:id/decision-readiness',methods:['GET'],roles:['brand']},
  {service:'catalog',path:'/v1/customization-requests/:id/decision',methods:['GET'],roles:[...participants]},
  {service:'catalog',path:'/v1/brand-decision-operations/:id',methods:['GET'],roles:[...participants]},
  {service:'catalog',path:'/v1/brand-decision-operations/:id/resume',methods:['POST'],roles:['brand']},
 ],slots:[],
} satisfies import('../registry-types').Registration;
