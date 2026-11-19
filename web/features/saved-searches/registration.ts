import type { Registration } from '@/registry-types';
import { en, ar } from './copy';
// Composition imports this additive registration when this route is released.
export default {lane:'L22',namespace:'saved-searches',routes:[],navigation:[],dictionaries:{en,ar},gateway:[
  {service:'communications',path:'/v1/saved-searches',methods:['GET'],roles:['buyer']},
  {service:'communications',path:'/v1/saved-searches/commands',methods:['POST'],roles:['buyer'],maxBodyBytes:8192,maxResponseBytes:16384},
  {service:'communications',path:'/v1/saved-searches/operations/:id',methods:['GET'],roles:['buyer']},
  {service:'communications',path:'/v1/saved-searches/notices',methods:['GET'],roles:['buyer']},
  {service:'communications',path:'/v1/saved-searches/notices/:id/read',methods:['POST'],roles:['buyer']},
  {service:'communications',path:'/v1/saved-searches/notices/:id/clear',methods:['POST'],roles:['buyer']},
  {service:'communications',path:'/v1/saved-searches/notices/:id/destination',methods:['GET'],roles:['buyer']}
]} satisfies Registration;
