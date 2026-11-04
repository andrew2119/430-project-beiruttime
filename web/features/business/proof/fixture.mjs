// Loopback-only synthetic transports for browser layout/interaction proofs.
// Never imported by the app. No production service or database is contacted.
import { createServer } from 'node:http';
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const at='2026-11-04T12:00:00Z';
const principal={actor:{subject_id:id(1),session_id:id(2),organization_id:null},roles:['buyer','operator','brand','dealer'],permissions:['identity.businesses.manage','identity.membership.manage','identity.private-seller.assign'],organizations:[id(3)],organization_grants:[]};
const session={access_token:'synthetic-browser-proof',token_type:'Bearer',expires_in:3600,account:{id:id(1),email:'sample@example.invalid',display_name:'Sample operator'},principal,access_fingerprint:'synthetic-browser-proof'};
const business={id:id(3),revision:1,public_name:'Sample Beirut Atelier',kind:'brand',state:'active',sample:true,capabilities:['sales','customization','servicing']};
const review={id:id(4),application_id:id(5),reviewer_id:id(1),state:'assigned',revision:1,application_revision:1,history:[{revision:1,state:'assigned',reason:'Sample independent review assignment',created_at:at}]};
const member={id:id(6),subject_id:id(1),state:'active',revision:1,intervention_scope:'Sample stock and records scope',capabilities:['business.stock.write'],qualifications:['Sample qualification']};
const caseRecord={id:id(7),target_kind:'listing',target_id:id(8),status:'assigned',revision:1,assigned_to:id(1),can_claim:true,can_release:true,can_decide:true,can_appeal:true,evidence:'Sample context only. No real evidence or finding.',review_signals:['duplicate_reports'],audit_older_available:false,last_action:null,delivery:'none',preserve_transaction_duties:true,audit:[{kind:'claim',reason:'Sample independent assignment',revision:1,created_at:at}]};
const intake={id:id(9),order_id:id(10),state:'received',revision:1,custody_receipt_id:id(11),custody_verification:'current',diagnosis_allowed:true,private_record:{serial:'SAMPLE-0001',reference:'Sample reference',movement:'Automatic',received_condition:'Sample condition record',accessories:'Sample box',reported_issue:'Sample timing issue',assessed_issue:'Awaiting diagnosis',diagnostic_opening_permission:true,no_polish_acknowledged:true,fee_acknowledged:true,fee_minor:2500,currency:'USD'}};
const queues=[{id:'verification',route:'/operations/verification',state:'ready',commands:true,items:[{id:id(4),status:'assigned',revision:1}],prerequisites:[]},{id:'inspection',route:'/operations/dashboard/queues/inspection',state:'awaiting_prerequisite',commands:false,items:[],prerequisites:['custody']},{id:'disputes',route:'/operations/dashboard/queues/disputes',state:'empty',commands:false,items:[],prerequisites:[]},{id:'quality',route:'/operations/dashboard/queues/quality',state:'unavailable',commands:false,items:[],prerequisites:[]}];
let mode='ready'; let challenge=null; const commands=[];
createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');const path=url.pathname;
 res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');
 const send=(data,status=200)=>{res.statusCode=status;res.end(JSON.stringify(data));};
 if(path==='/__proof/commands')return send(commands);
 if(path==='/__proof'){mode=url.searchParams.get('mode')??'ready';return send({mode});}
 if(!['GET','HEAD'].includes(req.method)&&!path.includes('/accounts/')) {
  let body='';for await(const chunk of req)body+=chunk;
  commands.push({path,method:req.method,body:body?JSON.parse(body):null,idempotency:req.headers['idempotency-key'],revision:req.headers['if-match']});
 }
 if(path==='/internal/v1/principal')return send(principal);
 if(path.includes('/accounts/refresh')||path.includes('/accounts/login'))return send(session);
 if(path.includes('/accounts/reauthenticate'))return send({proof:'synthetic-proof'});
 if(mode==='slow')await new Promise(resolve=>setTimeout(resolve,1200));
 if(mode==='error')return send({error:{code:'unavailable',request_id:'sample-proof-error',message:'Synthetic transport unavailable',details:{}}},503);
 if(path==='/v1/businesses'||path==='/v1/businesses/manage/records')return send({items:mode==='empty'?[]:[business]});
 if(path.endsWith('/memberships'))return send({items:mode==='empty'?[]:[member]});
 if(path==='/v1/contacts')return send({email:'sample@example.invalid',email_verified:true,email_sample:true,phone:'+96170000000',phone_verified:false,phone_sample:false,revision:1,pending_challenge:challenge});
 if(path==='/v1/contacts/challenges') {challenge={id:id(12),expires_at:'2026-11-05T12:00:00Z',delivery_mode:'sample_simulator'};return send(challenge);}
 if(path.endsWith('/sample-code'))return send({code:'123456'});
 if(path.endsWith('/verify')){challenge=null;return send({ok:true});}
 if(path==='/v1/private-reviews'||path==='/v1/private-reviews/mine')return send({items:mode==='empty'?[]:[review]});
 if(path.includes('/private-reviews/')&&path.endsWith('/evidence'))return send({items:[{id:id(13),kind:'identity',size:32},{id:id(14),kind:'possession',size:32}]});
 if(path.includes('/private-reviews/'))return send(review);
 if(path==='/v1/moderation/cases')return send({items:mode==='empty'?[]:[caseRecord],next_offset:null});
 if(path.includes('/moderation/cases/'))return send(caseRecord);
 if(path==='/v1/moderation/reports')return send({id:caseRecord.id});
 if(path==='/v1/operator-workspace/queues')return send({queues:mode==='empty'?[]:queues});
 if(path.includes('/operator-workspace/queues/'))return send(queues.find(q=>path.endsWith(q.id))??queues[0]);
 if(path.includes('/intake/records/')&&path.endsWith('/evidence'))return send({items:[{id:id(15),kind:'condition_photo',media_type:'image/png',size:100}]});
 if(path.includes('/intake/records/'))return send(intake);
 if(path==='/v1/intake/records')return send(req.method==='POST'?{id:intake.id}:{items:mode==='empty'?[]:[intake],next_offset:null});
 return send({ok:true});
}).listen(3358,'127.0.0.1',()=>console.log('Synthetic browser fixture: http://127.0.0.1:3358'));
