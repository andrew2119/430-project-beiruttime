import en from '../features/identity/en.json';
import ar from '../features/identity/ar.json';
import '../features/identity/styles.css';
import '../features/consent/styles.css';
import consentEn from '../features/consent/en.json';
import consentAr from '../features/consent/ar.json';
export default {
  lane:'L01', namespace:'identity',
  routes:[{path:'/account',roles:['public'],area:'account'},{path:'/seller/verification',roles:['buyer','private_seller'],area:'seller'},{path:'/consent',roles:['buyer'],area:'account'},{path:'/sample-tabs',roles:['public'],area:'account'}],
  navigation:[
    {id:'account',href:'/account',label:{en:'Account',ar:'حسابي'},order:70,area:'account',roles:['public'],bottom:true},
    {id:'private-verification',href:'/seller/verification',label:{en:'Private selling',ar:'البيع الفردي'},order:72,area:'seller',roles:['buyer','private_seller']},
    {id:'private-consent',href:'/consent',label:{en:'Private consent',ar:'الموافقة الخاصة'},order:74,area:'account',roles:['buyer']}
  ],
  dictionaries:{en:{...en,...Object.fromEntries(Object.entries(consentEn).map(([key,value])=>['consent_'+key,value]))},ar:{...ar,...Object.fromEntries(Object.entries(consentAr).map(([key,value])=>['consent_'+key,value]))}},
  gateway:[
    ...['register','login','refresh','logout','recovery','reset'].map(action=>({service:'identity' as const,path:`/v1/accounts/${action}`,methods:['POST' as const],roles:['public' as const],forwardCookies:['bt_refresh']})),
    // Switch-gated sample-account entry for one sample tab; Identity answers 404 while it is off.
    {service:'identity',path:'/v1/demo-entry/sessions',methods:['POST'],roles:['public'],forwardCookies:['bt_refresh'],maxBodyBytes:1024},
    {service:'identity',path:'/v1/accounts/me',methods:['GET'],roles:['buyer']},
    {service:'identity',path:'/v1/accounts/password',methods:['POST'],roles:['buyer']},
    {service:'identity',path:'/v1/accounts/reauthenticate',methods:['POST'],roles:['buyer']},
    {service:'identity',path:'/v1/private-seller/applications',methods:['POST'],roles:['buyer'],maxBodyBytes:900000},
    {service:'identity',path:'/v1/private-seller/applications/me',methods:['GET'],roles:['buyer']},
    {service:'identity',path:'/v1/private-seller/applications/:id/evidence/:evidenceId',methods:['GET'],roles:['buyer','operator']},
    {service:'eligibility',path:'/v1/consents',methods:['GET','POST'],roles:['buyer'],maxBodyBytes:450000},
    {service:'eligibility',path:'/v1/consents/:id/withdraw',methods:['POST'],roles:['buyer']},
    {service:'eligibility',path:'/v1/consents/:id/evidence/:evidenceId',methods:['GET'],roles:['operator']}
  ], slots:[]
} satisfies import('../registry-types').Registration;
