// Opt-in, loopback-only visual fixture. Never imported by the application.
// Exercises the real app/BFF/client markup without claiming connected money proofs.
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {quotePreviewExpired,quotePreviewTiming} from './fixture-quote-timing.mjs';
const MAX_QUOTE_MINOR=9_000_000_000_000;
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const now='2030-01-01T10:00:00Z',later='2099-01-01T12:00:00Z';
const principal={actor:{subject_id:id(1),session_id:id(2),organization_id:null},roles:['buyer','operator'],permissions:['orders.intake','orders.manage'],organizations:[],organization_grants:[]};
const session={access_token:'synthetic-visual-proof-only',token_type:'Bearer',expires_in:3600,account:{id:id(1),email:'visual@example.invalid',display_name:'Sample buyer'},principal,access_fingerprint:'visual-buyer'};
const quote={id:id(4),owner_id:id(1),subject_id:id(14),subject_revision:1,purpose:'purchase',currency:'USD',price_minor:500000,source:'sample',source_verified:false,revision:1,minor_unit_exponent:2,buyer_fee_minor:15000,seller_commission_minor:25000,seller_net_minor:475000,shipping_minor:0,tax_minor:0,payable_minor:515000,sample:true,...quotePreviewTiming(now),reviewed_at:null,rounding:'half_up',fx:null,commission_basis:'price_excluding_buyer_fee_shipping_tax',schedule_id:'usd-v2',policy:{revision:2,buyer_fee_bps:300,seller_commission_bps:500,shipping:'sample_zero',tax:'sample_zero',fx:'not_applied',currency_exponents:{USD:2,LBP:2}}};
const auctionWatchId=id(16);
const checkoutWatchId=id(6);
const checkoutQuote={...quote,id:id(21),source:'listing',source_verified:true,
  ...quotePreviewTiming(now),reviewed_at:now};
const heldQuote={...checkoutQuote,id:id(19),subject_id:id(18)};
const order={id:id(5),watch_id:id(17),listing_id:id(18),quote_id:heldQuote.id,is_demo:true,buyer_id:id(1),seller_id:id(7),organization_id:null,state:'awaiting_payment',revision:1,currency:'USD',total_minor:515000,deadline:later,payment_authority:false};
const maskedBidder=(auctionId,buyerId)=>'Bidder '+createHash('sha256').update(auctionId+':'+buyerId).digest('hex').slice(0,8);
const auction={id:id(8),listing_id:id(3),currency:'USD',opening_minor:400000,current_minor:0,next_minimum_minor:400000,increment_bands:[{from_minor:0,step_minor:10000}],starts_at:'2030-01-01T09:00:00Z',ends_at:'2030-01-02T10:00:00Z',server_time:now,revision:4,accepted_sequence:0,rules_version:'ordinary.v1',extension_policy:'none.v1',high_value_minor:1000000,reserve_set:false,leader:null,status:'live'};
const supportEnd='2030-01-01T09:30:00Z',supportAllocatedAt='2030-01-01T09:31:00Z';
const supportNotifiedAt='2030-01-01T09:32:00Z',supportAttemptAt='2030-01-01T09:33:00Z';
const supportMessageAt='2030-01-01T09:33:30Z',supportConfirmedAt='2030-01-01T09:34:00Z';
const supportCardDeadline=new Date(Date.parse(supportNotifiedAt)+48*60*60*1000).toISOString();
const supportAuction={...auction,status:'ended',mode:'closed_winner',ends_at:supportEnd,scheduled_ends_at:supportEnd,
  current_minor:500000,next_minimum_minor:510000,accepted_sequence:1,leader:maskedBidder(auction.id,id(1)),
  revision:5,end_version:1,close_version:1,first_bid_committed:true,listing_revision:1,bidding_version:'auction.proxy.v2'};
const auctionOrder={id:id(83),watch_id:auctionWatchId,listing_id:supportAuction.listing_id,
  quote_id:id(84),is_demo:true,buyer_id:id(1),seller_id:id(7),organization_id:null,currency:'USD',
  total_minor:515000,deadline:supportCardDeadline,notified_at:supportNotifiedAt,initiation_extended_until:supportCardDeadline,
  payment_method:'card',order_kind:'sale',notification_state:'notified',payment_authority:false};
const supportOrderHistory=[{revision:1,action:'allocate',reason:'Auction winner',occurred_at:supportAllocatedAt},
  {revision:2,action:'payment-notified',reason:'Payment notice retained',occurred_at:supportNotifiedAt},
  {revision:3,action:'payment-attempt',reason:'Simulated card attempt retained',occurred_at:supportAttemptAt}];
const supportConfirmation={revision:4,action:'payment-confirmed',reason:'Payment confirmed',occurred_at:supportConfirmedAt};
const supportOrderRevision=()=>supportResolved?supportConfirmation.revision:supportOrderHistory.at(-1).revision;
function acceptsFreshBid(serverTime) {
  const time=Date.parse(serverTime);
  return auction.status==='live'&&Date.parse(auction.starts_at)<=time&&time<Date.parse(auction.ends_at);
}
const maximumPath='/v1/auctions/'+auction.id+'/maximum';
let maximum=null, maximumPosts=0;
const initialAuction={...auction};
let leaderId=null;
const incumbentId=id(13);
const incumbentToken='Bearer synthetic-incumbent-token';
let bidHistory=[];
const seededQuotes=[[quote.id,quote],[heldQuote.id,heldQuote],[checkoutQuote.id,checkoutQuote]];
const quotes=new Map(seededQuotes);
const reservations=new Map();
const previews=new Map();
const reviews=new Map();
const quoteFields=['subject_id','subject_revision','purpose','currency','price_minor','schedule_id','source'];
const reviewFields=[...quoteFields,'quote_revision','payable_minor'];
const uuid=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const matches=(body,expected)=>Object.keys(body).length===Object.keys(expected).length&&
  Object.entries(expected).every(([field,value])=>body[field]===value);
function matchesBidQuote(preview,command,serverTime) {
  return preview?.reviewed_at&&preview.id===command.fee_quote_id&&
    preview.purpose==='bid'&&preview.subject_id===auction.id&&
    preview.subject_revision===command.expected_revision&&preview.currency===auction.currency&&
    preview.price_minor===command.amount_minor&&preview.sample===true&&
    preview.source==='sample'&&preview.source_verified===false&&!quotePreviewExpired(preview,serverTime);
}
const receipts=new Map();
const manualReceipts=new Map();
function recordPublicBid(bidderId,amount,automatic) {
  const bidder=maskedBidder(auction.id,bidderId);
  leaderId=bidderId;
  auction.current_minor=amount;
  auction.next_minimum_minor=amount+auction.increment_bands[0].step_minor;
  auction.leader=bidder;
  bidHistory.push({sequence:auction.accepted_sequence,bidder,amount_minor:amount,
    automatic,received_at:auction.server_time});
}
let mode='populated',optional=true,prefRevision=1;
const supportAttempts=new Map();
let supportSends=0,supportDeliveries=0,supportResolved=false;
function acceptSupportAttempt(attempt){
  attempt.accepted=true;
  attempt.sentAt=supportMessageAt;
  attempt.decidedRevision=supportOrderRevision()+(++supportSends);
}
let notices=[{recipient_id:id(1),id:id(9),kind:'outbid',resource_id:id(8),resource_revision:4,event_time:now,read_at:null,cleared_at:null,revision:1,required:true,sample:true,destination:'/buyer'}, {recipient_id:id(1),id:id(10),kind:'quote_ready',resource_id:id(4),resource_revision:1,event_time:now,read_at:now,cleared_at:null,revision:2,required:false,sample:true,destination:'/prices?quote_id='+id(4)}];
function inboxNotice(record) {
  const notice={...record};
  delete notice.recipient_id;
  return notice;
}
let drafts=[{id:id(11),subject_id:quote.subject_id,subject_revision:1,currency:'USD',amount_minor:420000,revision:1,updated_at:now,status:'draft'}];
const noticeSeed=structuredClone(notices),draftSeed=structuredClone(drafts);
export async function buyerFixture(req,res,readServerTime=()=>auction.server_time) {
  let raw='';for await(const chunk of req)raw+=chunk;
  const body=raw?JSON.parse(raw):{},url=new URL(req.url,'http://127.0.0.1'),path=url.pathname;
  const serverTime=readServerTime();
  const send=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  const fail=(status=503,code=status===401?'unauthorized':'unavailable')=>send({error:{code,message:'Synthetic visual state',request_id:'visual-proof-reference',details:{}}},status);
  if(path==='/__proof'){if(url.searchParams.has('reset')){supportAttempts.clear();supportSends=0;supportDeliveries=0;supportResolved=false;notices=structuredClone(noticeSeed);drafts=structuredClone(draftSeed);optional=true;prefRevision=1;maximum=null;maximumPosts=0;Object.assign(auction,initialAuction);leaderId=null;bidHistory=[];quotes.clear();for(const [key,value] of seededQuotes)quotes.set(key,value);reservations.clear();previews.clear();reviews.clear();receipts.clear();manualReceipts.clear();mode='populated';}if(url.searchParams.has('mode'))mode=url.searchParams.get('mode');
    if(url.searchParams.has('resolve-support')){
      if(!['support-committed','support-not-delivered'].includes(mode)) return fail(409);
      supportResolved=true;
    }
    return send({mode,maximumPosts,supportSends,supportDeliveries});
  }
  if(mode==='slow')await new Promise(resolve=>setTimeout(resolve,650));
  if(mode==='error')return fail();
  const authorization=req.headers.authorization;
  const actor=authorization===incumbentToken?incumbentId:
    authorization==='Bearer '+session.access_token?id(1):null;
  const scopedKey=key=>actor+':'+key;
  const ownedQuote=reference=>{
    const stored=quotes.get(reference);
    return stored?.owner_id===actor?stored:null;
  };
  if(path==='/internal/v1/principal')return mode==='signed-out'||!actor?fail(401):send(actor===incumbentId?{...principal,actor:{...principal.actor,subject_id:actor},roles:['buyer'],permissions:[]}:principal);
  if(path==='/v1/accounts/refresh')return mode==='signed-out'?fail(401):send(session);
  if(path==='/v1/accounts/me')return send(session.account);
  if(path==='/v1/orders/'+auctionOrder.id&&req.method==='GET'&&mode.startsWith('support-')){
    if(actor!==auctionOrder.buyer_id)return fail(actor?403:401);
    return send({order:{...auctionOrder,state:supportResolved?'paid_held':'payment_unknown',revision:supportOrderRevision()},
      history:supportResolved?[...supportOrderHistory,supportConfirmation]:supportOrderHistory});
  }
  const supportPath='/v1/support/auction-results/'+auction.id;
  if(mode.startsWith('support-')&&(path===supportPath||path.startsWith(supportPath+'/message-attempts/'))){
    if(actor!==id(1))return fail(actor?403:401);
    const conversation_id=id(81),revision=supportOrderRevision()+supportSends;
    if(path===supportPath&&req.method==='GET')return send({schema_version:1,auction_id:auction.id,buyer_id:actor,
      conversation_id,order_id:auctionOrder.id,revision,hold_state:supportResolved?'resolved':'active',
      assignment_state:'awaiting_operator',operator_id:null,
      follow_up_due_at:'2030-01-02T09:30:00Z',escalate_at:'2030-01-03T09:30:00Z',
      items:[...supportAttempts.values()].filter(attempt=>attempt.accepted).map((attempt,index)=>({sequence:index+1,author:'buyer',
        body:attempt.body,sent_at:attempt.sentAt})),next_cursor:null});
    const [operation_id,phase,...extra]=path.substring((supportPath+'/message-attempts/').length).split('/');
    if(req.method!=='POST'||extra.length||req.headers['idempotency-key']!==operation_id||body.conversation_id!==conversation_id)
      return fail(409);
    const answer=(state,revision)=>send({schema_version:1,auction_id:auction.id,buyer_id:actor,conversation_id,operation_id,state,revision});
    if(phase==='prepare'&&typeof body.body==='string'&&body.expected_revision===revision){
      if(supportResolved||supportAttempts.has(operation_id))return fail(409);
      supportAttempts.set(operation_id,{body:body.body,accepted:false,dispatched:false});
      return answer('prepared',revision);
    }
    if(!['deliver','check'].includes(phase)||Object.keys(body).length!==1)return fail(409);
    if(phase==='deliver') supportDeliveries++;
    const attempt=supportAttempts.get(operation_id);
    if(!attempt||attempt.abandoned){
      supportAttempts.set(operation_id,{abandoned:true});
      return answer('abandoned',revision);
    }
    if(attempt.accepted)return answer('accepted',attempt.decidedRevision);
    if(attempt.stale)return answer('stale',attempt.decidedRevision);
    if(supportResolved){attempt.stale=true;attempt.decidedRevision=revision;return answer('stale',revision);}
    if(phase==='check')return answer('prepared',revision);
    if(!attempt.dispatched){
      attempt.dispatched=true;
      if(mode==='support-committed')acceptSupportAttempt(attempt);
      return fail();
    }
    acceptSupportAttempt(attempt);
    return answer('accepted',attempt.decidedRevision);
  }
  if(path==='/v1/buyer-workspace'&&actor!==id(1))return fail(actor?403:401);
  const reservationPage={state:'available',next_cursor:null,items:mode==='empty'?[]:[{reservation_id:id(5),listing_id:order.listing_id,state:'awaiting_payment',total_minor:515000,currency:'USD',revision:1,expires_at:later,is_demo:true,payment_available:false,delivery_available:false}]};
  if(path==='/v1/buyer-workspace'&&url.searchParams.get('section')==='reservations')return send(reservationPage);
  if(path==='/v1/buyer-workspace'&&!url.searchParams.has('view'))return send({version:1,as_of:now,final_results_available:false,bids:{state:'available',next_cursor:null,items:mode==='empty'||maximum===null?[]:[{auction_id:auction.id,listing_id:auction.listing_id,status:'leading',current_price_minor:auction.current_minor,currency:'USD',revision:auction.revision,ends_at:auction.ends_at,is_demo:true}]},reservations:reservationPage});
  if(path==='/v1/buyer-workspace'&&req.method==='GET'){
    const view=url.searchParams.get('view');
    if(mode.startsWith('support-')&&view==='won')return send({schema_version:2,state:'available',total:1,next_cursor:null,items:[{
      auction_id:supportAuction.id,listing_id:supportAuction.listing_id,watch_id:auctionWatchId,revision:2,currency:'USD',is_demo:true,
      state:'won',final_minor:supportAuction.current_minor,ended_at:supportEnd,order_id:auctionOrder.id,
      financial_state:supportResolved?'paid_held':'unknown',completed_sale:false,next_action:supportResolved?'review_order':'contact_support',
    }]});
    const items=mode==='empty'||(view!=='calendar'&&(view!=='leading'||maximum===null))?[]:[{
      auction_id:auction.id,listing_id:auction.listing_id,status:maximum===null?null:'leading',lifecycle:'live',
      current_price_minor:auction.current_minor,currency:'USD',revision:auction.revision,
      starts_at:auction.starts_at,ends_at:auction.ends_at,is_demo:true,
    }];
    return send({schema_version:2,state:'available',items,total:items.length,next_cursor:null});
  }
  if(path==='/v2/auctions/'+auction.id)return send(mode.startsWith('support-')?supportAuction:{...auction,mode:'bidding'});
  if(path==='/v1/auctions/'+auction.id){
    if(!mode.startsWith('support-'))return send(auction);
    return send({...auction,status:supportAuction.status,ends_at:supportEnd,revision:supportAuction.revision,
      current_minor:supportAuction.current_minor,next_minimum_minor:supportAuction.next_minimum_minor,
      accepted_sequence:supportAuction.accepted_sequence,leader:supportAuction.leader});
  }
  if(path.startsWith('/v1/auction-operations/by-key/')&&req.method==='GET'){
    const operation=receipts.get(scopedKey(path.split('/').at(-1)));
    return operation?send(operation.receipt):fail(404);
  }
  if(path==='/v1/auctions'||path==='/v2/auctions') {
    const item=path.startsWith('/v2/')?{...auction,mode:'bidding'}:auction;
    return send({items:!url.searchParams.has('listing_id')||url.searchParams.get('listing_id')===auction.listing_id?[item]:[]});
  }
  if(path==='/v1/auctions/'+auction.id+'/history'){
    const after=Number(url.searchParams.get('after_sequence')??0);
    const items=bidHistory.filter(bid=>bid.sequence>after);
    return send({snapshot:auction,items,has_more:false,next_sequence:items.at(-1)?.sequence??after});
  }
  const isIncumbent=actor===incumbentId;
  if(path===maximumPath&&!actor)return fail(401);
  if(path==='/v1/auctions/'+auction.id+'/bids'&&req.method==='POST'){
    if(!isIncumbent)return fail(403);
    const key=req.headers['idempotency-key'];
    if(!key)return fail(422);
    const prior=manualReceipts.get(key);
    if(prior)return JSON.stringify(prior.body)===JSON.stringify(body)?send(prior.receipt):fail(409);
    const incumbentQuote=ownedQuote(body.fee_quote_id);
    if(!acceptsFreshBid(serverTime)||auction.accepted_sequence!==0||body.expected_revision!==auction.revision||
      body.amount_minor!==auction.opening_minor||!matchesBidQuote(incumbentQuote,body,serverTime))return fail(409);
    auction.accepted_sequence++;
    auction.revision++;
    recordPublicBid(actor,body.amount_minor,false);
    const receipt={operation_id:id(15),auction_id:auction.id,revision:auction.revision,
      status:'succeeded',code:'bid_accepted',current_minor:auction.current_minor};
    manualReceipts.set(key,{body,receipt});
    return send(receipt);
  }
  if(path===maximumPath&&req.method==='POST'&&body.action==='read_v2'){
    return send({schema_version:2,auction_id:auction.id,actor_id:actor,
      watch_id:auctionWatchId,revision:auction.revision,amount_minor:isIncumbent?null:maximum,
      active:!isIncumbent&&maximum!==null,
      standing:bidHistory.some(row=>row.bidder===maskedBidder(auction.id,actor))
        ?auction.leader===maskedBidder(auction.id,actor)?'leading':'outbid':null});
  }
  if(path===maximumPath&&req.method==='POST'&&body.action==='submit_v2'){
    if(isIncumbent)return fail(403);
    const command=body.command;
    const key=req.headers['idempotency-key'];
    const positive=value=>Number.isSafeInteger(value)&&value>0;
    if(!uuid.test(key??'')||!command||Object.keys(command).length!==6||
      !positive(command.amount_minor)||command.amount_minor>9_000_000_000_000_000||
      !positive(command.expected_revision)||!positive(command.quote_revision)||
      !uuid.test(command.fee_quote_id)||!uuid.test(command.watch_id)||
      typeof command.policy_revision!=='string'||!command.policy_revision.length||command.policy_revision.length>100)return fail(422);
    maximumPosts++;
    const receiptKey=scopedKey(key);
    const prior=receipts.get(receiptKey);
    if(prior&&!matches(command,prior.body))return fail(409);
    if(!prior){
      const preview=ownedQuote(command.fee_quote_id);
      const state=command.expected_revision!==auction.revision?'stale':
        !acceptsFreshBid(serverTime)||!matchesBidQuote(preview,command,serverTime)||
        command.watch_id!==auctionWatchId||command.quote_revision!==preview.revision||
        command.policy_revision!==String(preview.policy.revision)||
        (maximum===null?command.amount_minor<auction.next_minimum_minor:command.amount_minor<=maximum)?
          'denied':mode==='pending-maximum'?'pending':'accepted';
      if(state==='accepted'){
        const previousLeaderId=leaderId;
        auction.accepted_sequence++;
        auction.revision++;
        if(maximum===null)recordPublicBid(actor,auction.next_minimum_minor,true);
        maximum=command.amount_minor;
        if(previousLeaderId&&previousLeaderId!==leaderId){
          notices.push({recipient_id:previousLeaderId,id:randomUUID(),kind:'outbid',
            resource_id:auction.id,resource_revision:auction.revision,event_time:serverTime,
            read_at:null,cleared_at:null,revision:1,required:true,sample:true,destination:'/buyer'});
        }
      }
      receipts.set(receiptKey,{body:command,receipt:{schema_version:2,operation_id:key,actor_id:actor,
        organization_id:null,subject_id:auction.id,watch_id:command.watch_id,
        expected_revision:command.expected_revision,revision:auction.revision,quote_id:command.fee_quote_id,
        quote_revision:command.quote_revision,policy_revision:command.policy_revision,state,
        pending_reason:state==='pending'?'response_lost':null,next_actor:null,next_review_at:null}});
    }
    return send(receipts.get(receiptKey).receipt);
  }
  if(path===maximumPath&&req.method==='POST'&&body.action==='list_bid_receipts_v1'){
    return body.before?fail(409):send({auction_id:auction.id,items:[],next_cursor:null});
  }
  if(path===maximumPath&&req.method==='POST'&&body.action==='lookup_v2'){
    const operation=receipts.get(scopedKey(body.operation_id));
    return operation?send(operation.receipt):fail(404);
  }
  const checkoutOrder=reservations.values().next().value?.receipt.order;
  const checkout={watch_id:checkoutWatchId,listing_id:quote.subject_id,sale_mode:'fixed',
    status:checkoutOrder?'reserved':'available',revision:checkoutOrder?2:1,is_demo:true};
  if(path.endsWith('/availability')){
    const stock=[checkout,{watch_id:order.watch_id,listing_id:order.listing_id,sale_mode:'fixed',
      status:'reserved',revision:order.revision,is_demo:true},
    {watch_id:auctionWatchId,listing_id:auction.listing_id,sale_mode:'auction',
      status:'available',revision:auction.revision,is_demo:true}];
    const record=stock.find(row=>path==='/v1/watches/'+row.watch_id+'/availability'||
      path==='/v1/listings/'+row.listing_id+'/availability');
    return record?send(record):fail(404);
  }
  const orderDetail=/^\/v1\/orders\/([^/]+)$/.exec(path);
  if(req.method==='GET'&&(path==='/v1/orders'||orderDetail)){
    if(mode==='signed-out'||!actor)return fail(401);
    const orders=[order,...(checkoutOrder?[checkoutOrder]:[])];
    const participates=row=>row.buyer_id===actor||row.seller_id===actor;
    if(!orderDetail)return send({items:mode==='empty'?[]:orders.filter(participates)});
    const record=orders.find(row=>row.id===orderDetail[1]);
    if(!record)return fail(404,'not_found');
    if(!participates(record))return fail(403,'forbidden');
    return send({order:record,history:[{action:'reserve',reason:'sample',revision:1,occurred_at:now}]});
  }
  if(path==='/v1/reservations'&&req.method==='POST'){
    if(actor!==id(1))return fail(actor?403:401);
    const key=req.headers['idempotency-key'];
    if(!key)return fail(422);
    const saved=reservations.get(key);
    if(saved)return matches(body,saved.body)?send(saved.receipt):fail(409);
    if(checkoutOrder||!matches(body,{watch_id:checkout.watch_id,quote_id:body.quote_id,
      expected_revision:checkout.revision}))return fail(409);
    const purchase=ownedQuote(body.quote_id);
    if(purchase?.source!=='listing'||purchase.source_verified!==true||purchase.purpose!=='purchase'||
      purchase.subject_id!==checkout.listing_id||purchase.subject_revision!==checkout.revision||
      purchase.currency!=='USD'||purchase.price_minor!==checkoutQuote.price_minor||
      !purchase.reviewed_at||quotePreviewExpired(purchase,serverTime))return fail(409,'quote_not_authoritative');
    const reserved={...order,id:id(20),watch_id:checkout.watch_id,listing_id:checkout.listing_id,
      quote_id:purchase.id,total_minor:purchase.payable_minor};
    const receipt={id:id(12),request_id:'visual-reserve',status:'succeeded',resource_id:reserved.id,order:reserved};
    reservations.set(key,{body,receipt});
    return send(receipt);
  }
  if(path.endsWith('/transitions')||path.endsWith('/intake'))return send({id:id(12),request_id:'visual-operation',status:'succeeded',resource_id:id(5)});
  if(path==='/v1/quotes'||path.startsWith('/v1/quotes/')){
    if(!actor)return fail(401);
    if(path==='/v1/quotes'&&req.method==='GET'){
      return send({items:mode==='empty'?[]:[...quotes.values()].filter(value=>value.owner_id===actor)});
    }
    const key=req.headers['idempotency-key'];
    if(path==='/v1/quotes'&&req.method==='POST'){
      if(!key)return fail(422);
      const prior=previews.get(scopedKey(key));
      if(prior)return matches(body,prior.body)?send(ownedQuote(prior.id)):fail(409,'idempotency_conflict');
      const price=body.price_minor;
      if(!Number.isSafeInteger(price)||price<=0||price>MAX_QUOTE_MINOR)return fail(422);
      const bid=body.purpose==='bid';
      if(bid&&(body.subject_id!==auction.id||body.subject_revision!==auction.revision||
        body.currency!=='USD'||body.source!=='sample'||body.schedule_id!==quote.schedule_id))return fail(422);
      const fee=rate=>Number((BigInt(price)*BigInt(rate)+50n)/100n);
      const buyerFee=fee(3),sellerFee=fee(5);
      const binding=Object.fromEntries(quoteFields.map(field=>[field,body[field]]));
      const preview={...quote,...binding,...quotePreviewTiming(serverTime),
        id:randomUUID(),owner_id:actor,buyer_fee_minor:buyerFee,seller_commission_minor:sellerFee,
        seller_net_minor:price-sellerFee,payable_minor:price+buyerFee};
      quotes.set(preview.id,preview);
      previews.set(scopedKey(key),{id:preview.id,body});
      return send(preview);
    }
    const [, , ,reference,action]=path.split('/');
    const preview=ownedQuote(reference);
    if(!preview)return send({error:{code:'not_found',message:'Quote not found.',
      request_id:'visual-proof-reference',details:{}}},404);
    if(!action&&req.method==='GET')return send(preview);
    if(action==='review'&&req.method==='POST'){
      if(!key)return fail(422);
      const binding=Object.fromEntries(quoteFields.map(field=>[field,preview[field]]));
      if(Object.keys(body).length!==reviewFields.length||reviewFields.some(field=>!Object.hasOwn(body,field)))return fail(422);
      if(!matches(body,{...binding,quote_revision:preview.revision,payable_minor:preview.payable_minor}))
        return fail(409,'quote_binding_mismatch');
      const prior=reviews.get(scopedKey(key));
      if(prior===reference)return send(preview);
      if(prior||preview.reviewed_at)return fail(409,'idempotency_conflict');
      if(quotePreviewExpired(preview,serverTime))return fail(409,'quote_expired');
      preview.reviewed_at=serverTime;
      reviews.set(scopedKey(key),reference);
      return send(preview);
    }
    return fail(404);
  }
  if(path==='/v1/buying/readiness')return send({release:{payment:false,send_offer:false,accept_offer:false},routes:[{id:'card',label:{en:'Card payment',ar:'الدفع بالبطاقة'},released:false}],reservation:{status:url.searchParams.has('reservation_id')?'available':'not_selected',...(url.searchParams.has('reservation_id')?{record:order}:{})},quote:{status:url.searchParams.has('quote_id')?'available':'not_selected',...(url.searchParams.has('quote_id')?{record:quote}:{})},drafts:mode==='empty'?[]:drafts});
  if(path.startsWith('/v1/buying/drafts')){const draft={...drafts[0],...body,revision:2};drafts=[draft];return send(draft);}
  if(path==='/v1/inbox/preferences'){if(req.method==='PUT'){optional=body.optional_enabled;prefRevision++;}return send({optional_enabled:optional,revision:prefRevision});}
  if(path==='/v1/inbox'||path.startsWith('/v1/inbox/')){
    if(mode==='signed-out'||!actor)return fail(401);
    const owned=notices.filter(notice=>notice.recipient_id===actor);
    if(path==='/v1/inbox'){
      const visible=mode==='empty'?[]:owned.filter(notice=>!notice.cleared_at);
      return send({items:visible.map(inboxNotice),
        unread_count:visible.filter(notice=>!notice.read_at).length,next_cursor:null});
    }
    const [, , ,noticeId,action]=path.split('/');
    const notice=owned.find(row=>row.id===noticeId);
    if(!notice)return fail(404);
    if(action==='destination')return send({url:notice.destination});
    if(action==='read')notice.read_at=serverTime;
    if(action==='clear')notice.cleared_at=serverTime;
    notice.revision++;
    return send(inboxNotice(notice));
  }
  if(path.startsWith('/health/'))return send({status:'ok'});
  return fail(404);
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
http.createServer(buyerFixture).listen(Number(process.env.BT_BUYER_FIXTURE_PORT??33516),'127.0.0.1',()=>console.log('Synthetic buyer visual fixture listening on loopback only'));

// Screenshot requests need the theme cookie on the upstream request.
// Stamp the real SSR theme cookies upstream, without changing application code.
let shotTheme='light',reference=false;
http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(url.pathname==='/__shot'){shotTheme=url.searchParams.get('theme')==='dark'?'dark':'light';reference=url.searchParams.get('reference')==='1';res.end('Screenshot transport configured');return;}
  const headers={...req.headers,cookie:`${req.headers.cookie??''}; bt-theme=${shotTheme}`};
  const upstream=http.request({host:'127.0.0.1',port:reference?33515:33517,path:req.url,method:req.method,headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res);});
  upstream.on('error',()=>{res.writeHead(503);res.end('Visual server unavailable');});req.pipe(upstream);
}).listen(33519,'127.0.0.1');
}
