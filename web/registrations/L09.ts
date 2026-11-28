import en from '../features/moderation/en.json';
import ar from '../features/moderation/ar.json';
import '../features/moderation/styles.css';
import type { Registration, Role } from '../registry-types';
const accounts:Role[]=['buyer','private_seller','dealer','brand','operator'];
export default {
  lane:'L09',namespace:'operations',
  routes:[
    {path:'/operations/moderation',roles:accounts,area:'operator'},
    {path:'/operations/dashboard',roles:['operator'],area:'operator'},
    {path:'/operations/dashboard/queues/:key',roles:['operator'],area:'operator'},
    {path:'/business-intake',roles:['brand','dealer'],area:'seller'}
  ],
  navigation:[
    {id:'operator-desk',href:'/operations/dashboard',label:{en:'Operations',ar:'العمليات'},order:70,area:'operator',roles:['operator'],bottom:true},
    {id:'moderation',href:'/operations/moderation',label:{en:'Trust & safety',ar:'الثقة والسلامة'},order:71,area:'operator',roles:['operator']},
    {id:'business-intake',href:'/business-intake',label:{en:'Technical intake',ar:'الاستلام الفني'},order:72,area:'seller',roles:['dealer','brand']}
  ],
  dictionaries:{en,ar},
  gateway:[
    {service:'trust',path:'/v1/moderation/reports',methods:['POST'],roles:accounts,maxBodyBytes:32768},
    {service:'trust',path:'/v1/moderation/cases',methods:['GET'],roles:['operator']},
    {service:'trust',path:'/v1/moderation/cases/:id',methods:['GET'],roles:accounts},
    {service:'trust',path:'/v1/moderation/cases/:id/claim',methods:['POST'],roles:['operator']},
    {service:'trust',path:'/v1/moderation/cases/:id/release',methods:['POST'],roles:['operator'],maxBodyBytes:32768},
    {service:'trust',path:'/v1/moderation/cases/:id/decisions',methods:['POST'],roles:['operator'],maxBodyBytes:32768},
    {service:'trust',path:'/v1/moderation/cases/:id/appeals',methods:['POST'],roles:accounts,maxBodyBytes:32768},
    {service:'communications',path:'/v1/operator-workspace/queues',methods:['GET'],roles:['operator']},
    {service:'communications',path:'/v1/operator-workspace/queues/:key',methods:['GET'],roles:['operator']},
    {service:'service-operations',path:'/v1/intake/records',methods:['GET','POST'],roles:['dealer','brand'],maxBodyBytes:65536},
    {service:'service-operations',path:'/v1/intake/records/:id',methods:['GET','PUT'],roles:['dealer','brand'],maxBodyBytes:65536},
    {service:'service-operations',path:'/v1/intake/operations/:key',methods:['GET','DELETE'],roles:['dealer','brand'],maxBodyBytes:4096,maxResponseBytes:8192},
    {service:'service-operations',path:'/v1/intake/records/:id/evidence',methods:['GET','POST'],roles:['dealer','brand'],maxBodyBytes:524288},
    {service:'service-operations',path:'/v1/intake/evidence/:id',methods:['GET'],roles:['dealer','brand'],maxResponseBytes:524288}
  ],slots:[]
} satisfies Registration;
