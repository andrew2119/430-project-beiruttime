import en from '../features/brand-options/en.json';
import ar from '../features/brand-options/ar.json';
import '../features/brand-options/styles.css';
export default {
  lane: 'L10', namespace: 'brand-options',
  routes: [{ path: '/customize', roles: ['public'], area: 'storefront' }],
  navigation: [{ id: 'brand-options', href: '/customize', label: { en: 'Personalize', ar: 'خصّص ساعتك' }, order: 40, area: 'storefront', roles: ['public'] }],
  dictionaries: { en, ar },
  gateway: [
    {service:'catalog',path:'/v1/brand-options/brands',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/brand-options/brands/:brand',methods:['GET'],roles:['public']},
    {service:'catalog',path:'/v1/brand-options/brands/:brand/:kind/:option',methods:['PUT'],roles:['brand']},
    {service:'catalog',path:'/v1/brand-options/configurations',methods:['GET'],roles:['buyer']},
    {service:'catalog',path:'/v1/brand-options/configurations/:id',methods:['GET'],roles:['buyer']},
    {service:'catalog',path:'/v1/brand-options/configurations/:id/:kind',methods:['PUT'],roles:['buyer']},
    {service:'catalog',path:'/v1/brand-options/configurations/:id/references',methods:['POST'],roles:['buyer'],maxBodyBytes:1048576},
    {service:'catalog',path:'/v1/brand-options/configurations/:id/references/:reference',methods:['GET'],roles:['buyer'],maxResponseBytes:1048576},
  ],
} satisfies import('../registry-types').Registration;
