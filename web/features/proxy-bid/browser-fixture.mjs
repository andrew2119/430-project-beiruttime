// Opt-in, loopback-only visual fixture. Never imported by the application.
// Exercises the real app/BFF/client markup without claiming connected money proofs.
import http from 'node:http';
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const now='2030-01-01T10:00:00Z',later='2099-01-01T12:00:00Z';
const principal={actor:{subject_id:id(1),session_id:id(2),organization_id:null},roles:['buyer','operator'],permissions:['orders.intake','orders.manage'],organizations:[],organization_grants:[]};
const session={access_token:'synthetic-visual-proof-only',token_type:'Bearer',expires_in:3600,account:{id:id(1),email:'visual@example.invalid',display_name:'Sample buyer'},principal,access_fingerprint:'visual-buyer'};
const quote={id:id(4),owner_id:id(1),subject_id:id(3),subject_revision:1,purpose:'purchase',currency:'USD',price_minor:500000,source:'sample',source_verified:false,revision:1,minor_unit_exponent:2,buyer_fee_minor:15000,seller_commission_minor:25000,seller_net_minor:475000,shipping_minor:0,tax_minor:0,payable_minor:515000,sample:true,created_at:now,expires_at:later,reviewed_at:null,rounding:'half_up',fx:null,commission_basis:'price_excluding_buyer_fee_shipping_tax',schedule_id:'usd-v2',policy:{revision:2,buyer_fee_bps:300,seller_commission_bps:500,shipping:'sample_zero',tax:'sample_zero',fx:'not_applied',currency_exponents:{USD:2,LBP:2}}};
const order={id:id(5),watch_id:id(6),listing_id:id(3),quote_id:id(4),is_demo:true,buyer_id:id(1),seller_id:id(7),organization_id:null,state:'awaiting_payment',revision:1,currency:'USD',total_minor:515000,deadline:later,payment_authority:false};
const auction={id:id(8),listing_id:id(3),currency:'USD',opening_minor:400000,current_minor:400000,next_minimum_minor:410000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2020-01-01T00:00:00Z',ends_at:later,server_time:now,revision:4,accepted_sequence:1,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:'bidder-1',status:'live'};
let mode='populated',optional=true,prefRevision=1,currentQuote=quote;
let notices=[{id:id(9),kind:'outbid',resource_id:id(8),resource_revision:4,event_time:now,read_at:null,cleared_at:null,revision:1,required:true,sample:true,destination:'/buyer'}, {id:id(10),kind:'quote_ready',resource_id:id(4),resource_revision:1,event_time:now,read_at:now,cleared_at:null,revision:2,required:false,sample:true,destination:'/prices?quote_id='+id(4)}];
let drafts=[{id:id(11),subject_id:id(3),subject_revision:1,currency:'USD',amount_minor:420000,revision:1,updated_at:now,status:'draft'}];
const noticeSeed=structuredClone(notices),draftSeed=structuredClone(drafts);
const server=http.createServer(async(req,res)=>{
  let raw='';for await(const chunk of req)raw+=chunk;
  const body=raw?JSON.parse(raw):{},url=new URL(req.url,'http://127.0.0.1'),path=url.pathname;
  const send=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  const fail=(status=503)=>send({error:{code:status===401?'unauthorized':'unavailable',message:'Synthetic visual state',request_id:'visual-proof-reference',details:{}}},status);
  if(path==='/__proof'){if(url.searchParams.has('reset')){notices=structuredClone(noticeSeed);drafts=structuredClone(draftSeed);currentQuote=quote;optional=true;prefRevision=1;mode='populated';}if(url.searchParams.has('mode'))mode=url.searchParams.get('mode');return send({mode});}
  if(mode==='slow')await new Promise(resolve=>setTimeout(resolve,650));
  if(mode==='error')return fail();
  if(path==='/internal/v1/principal')return mode==='signed-out'?fail(401):send(principal);
  if(path==='/v1/accounts/refresh')return mode==='signed-out'?fail(401):send(session);
  if(path==='/v1/accounts/me')return send(session.account);
  if(path==='/v1/buyer-workspace')return send({version:1,as_of:now,final_results_available:false,bids:{state:'available',next_cursor:null,items:mode==='empty'?[]:[{auction_id:id(8),listing_id:id(3),status:'leading',current_price_minor:400000,currency:'USD',revision:4,ends_at:later,is_demo:true}]},reservations:{state:'available',next_cursor:null,items:mode==='empty'?[]:[{reservation_id:id(5),listing_id:id(3),state:'awaiting_payment',total_minor:515000,currency:'USD',revision:1,expires_at:later,is_demo:true,payment_available:false,delivery_available:false}]}});
  if(path==='/v1/auctions')return send({items:[auction]});
  if(path.endsWith('/maximum'))return send({id:id(12),status:'succeeded',resource_id:id(8)});
  if(path.endsWith('/availability'))return send({watch_id:id(6),listing_id:id(3),sale_mode:'fixed',status:'available',revision:1,is_demo:true});
  if(path==='/v1/orders')return send({items:mode==='empty'?[]:[order]});
  if(path==='/v1/orders/'+id(5))return send({order,history:[{action:'reserve',reason:'sample',revision:1,occurred_at:now}]});
  if(path==='/v1/reservations')return send({id:id(12),request_id:'visual-reserve',status:'succeeded',resource_id:id(5),order});
  if(path.endsWith('/transitions')||path.endsWith('/intake'))return send({id:id(12),request_id:'visual-operation',status:'succeeded',resource_id:id(5)});
  if(path==='/v1/quotes'&&req.method==='GET')return send({items:mode==='empty'?[]:[currentQuote]});
  if(path==='/v1/quotes'&&req.method==='POST'){currentQuote={...quote,...body};return send(currentQuote);}
  if(path.startsWith('/v1/quotes/')){if(path.endsWith('/review'))currentQuote={...currentQuote,reviewed_at:now};return send(currentQuote);}
  if(path==='/v1/buying/readiness')return send({release:{payment:false,send_offer:false,accept_offer:false},routes:[{id:'card',label:{en:'Card payment',ar:'الدفع بالبطاقة'},released:false}],reservation:{status:url.searchParams.has('reservation_id')?'available':'not_selected',...(url.searchParams.has('reservation_id')?{record:order}:{})},quote:{status:url.searchParams.has('quote_id')?'available':'not_selected',...(url.searchParams.has('quote_id')?{record:quote}:{})},drafts:mode==='empty'?[]:drafts});
  if(path.startsWith('/v1/buying/drafts')){const draft={...drafts[0],...body,revision:2};drafts=[draft];return send(draft);}
  if(path==='/v1/inbox/preferences'){if(req.method==='PUT'){optional=body.optional_enabled;prefRevision++;}return send({optional_enabled:optional,revision:prefRevision});}
  if(path==='/v1/inbox')return send({items:mode==='empty'?[]:notices.filter(n=>!n.cleared_at),unread_count:notices.filter(n=>!n.read_at&&!n.cleared_at).length,next_cursor:null});
  if(path.startsWith('/v1/inbox/')){const notice=notices.find(n=>path.includes(n.id));if(!notice)return fail(404);if(path.endsWith('/destination'))return send({url:notice.destination});if(path.endsWith('/read'))notice.read_at=now;if(path.endsWith('/clear'))notice.cleared_at=now;notice.revision++;return send(notice);}
  if(path.startsWith('/health/'))return send({status:'ok'});
  return fail(404);
});
server.listen(Number(process.env.BT_BUYER_FIXTURE_PORT??33516),'127.0.0.1',()=>console.log('Synthetic buyer visual fixture listening on loopback only'));

// Screenshot-only transport: the headless Chrome CLI cannot accept cookies.
// Stamp the real SSR theme cookies upstream, without changing application code.
let shotTheme='light',reference=false;
http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(url.pathname==='/__shot'){shotTheme=url.searchParams.get('theme')==='dark'?'dark':'light';reference=url.searchParams.get('reference')==='1';res.end('Screenshot transport configured');return;}
  const headers={...req.headers,cookie:`${req.headers.cookie??''}; bt-theme=${shotTheme}`};
  const upstream=http.request({host:'127.0.0.1',port:reference?33515:33517,path:req.url,method:req.method,headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res);});
  upstream.on('error',()=>{res.writeHead(503);res.end('Visual server unavailable');});req.pipe(upstream);
}).listen(33519,'127.0.0.1');
