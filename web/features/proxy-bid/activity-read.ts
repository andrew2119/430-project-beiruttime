import type {ActivityView,CurrentActivity} from '@contracts/contracts-comms/buyer-workspace';
import {ApiError} from '@/lib/api/client';
import {definePageRead} from '@/lib/page-speed/definition';
import {authenticatedRequest} from './session';

const reference=(value:unknown)=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const integer=(value:unknown,min:number,max=Number.MAX_SAFE_INTEGER)=>
  typeof value==='number'&&Number.isSafeInteger(value)&&value>=min&&value<=max;
const minor=(value:unknown,min:number)=>integer(value,min,9_000_000_000_000_000);
const utc=(value:unknown)=>typeof value==='string'&&/T.*(?:Z|\+00:00)$/.test(value)&&Number.isFinite(Date.parse(value));
const commonFields=['auction_id','listing_id','revision','currency','is_demo'];
const bidFields=new Set([...commonFields,'status','lifecycle','current_price_minor','starts_at','ends_at','listing_title']);
const resultFields=new Set([...commonFields,'watch_id','state','final_minor','ended_at','order_id',
  'financial_state','allocation_state','completed_sale','next_action']);
const paymentStates=['pending','unknown','paid_held','unpaid','unpaid_released','released'];

function validRow(value:unknown, view:ActivityView) {
  if(!value||typeof value!=='object'||Array.isArray(value)) return false;
  const row=value as Record<string,unknown>;
  if(!reference(row.auction_id)||!reference(row.listing_id)||!integer(row.revision,1)||
    row.currency!=='USD'||typeof row.is_demo!=='boolean') return false;

  if(view==='leading'||view==='outbid'||view==='calendar') {
    if(Object.keys(row).some(key=>!bidFields.has(key))||!minor(row.current_price_minor,0)||!utc(row.starts_at)||!utc(row.ends_at)) return false;
    const title=row.listing_title;
    if(title!==undefined&&title!==null&&
      (typeof title!=='string'||!title.length||Array.from(title).length>240)) return false;
    const duration=Date.parse(row.ends_at as string)-Date.parse(row.starts_at as string);
    if(duration<=0||duration>90*86_400_000) return false;
    if(row.current_price_minor===0&&row.status!==null) return false;
    if(view!=='calendar') return row.lifecycle==='live'&&row.status===view;
    return row.lifecycle==='scheduled'?row.status===null&&row.current_price_minor===0:
      row.lifecycle==='live'&&(row.status===null||row.status==='leading'||row.status==='outbid');
  }

  if(Object.keys(row).some(key=>!resultFields.has(key))||!reference(row.watch_id)||!utc(row.ended_at)||typeof row.completed_sale!=='boolean'||
    (row.order_id!==null&&!reference(row.order_id))) return false;
  const state=row.state;
  if(state!=='won'&&state!=='lost'&&state!=='no_sale') return false;
  if(!minor(row.final_minor,1)&&!(state==='no_sale'&&row.final_minor===null)) return false;
  const financial=row.financial_state;
  if('allocation_state' in row) {
    if(row.allocation_state!=='denied'||state==='no_sale'||financial!==null||row.order_id!==null||row.completed_sale) return false;
  } else if(state==='won') {
    if(typeof financial!=='string'||!paymentStates.includes(financial)||
      (financial!=='pending'&&row.order_id===null)||row.completed_sale!==(financial==='released')) return false;
  } else if(financial!==null||row.order_id!==null||(state==='no_sale'&&row.completed_sale)) return false;
  const action=financial==='unknown'||(state==='won'&&row.order_id===null)?'contact_support':
    row.order_id!==null?'review_order':'view_auction';
  return row.next_action===action&&(
    view==='released'?row.completed_sale:view==='unpaid'?
      financial==='unpaid'||financial==='unpaid_released':state===view);
}

function validPage(page:CurrentActivity,view:ActivityView,cursor:string|null) {
  if(page?.schema_version!==2||!Array.isArray(page.items)||page.items.length>50) return false;
  const {state,items,total,next_cursor:next}=page;
  if(next!==null&&(typeof next!=='string'||!next.length||next.length>200||next===cursor)) return false;
  if(state==='unavailable') return items.length===0&&total===null&&next===null;
  if(state!=='available'||total===null||!integer(total,items.length)||
    (next!==null&&(!items.length||total===items.length))||(cursor!==null&&!items.length)||(!cursor&&(next!==null)!==(total>items.length))) return false;
  return items.every(row=>validRow(row,view))&&
    new Set(items.map(row=>row.auction_id.toLowerCase())).size===items.length;
}

type ActivityPage = CurrentActivity;
export type ActivityPageBoundary = {
  cursor: string | null;
  state: ActivityPage['state'];
  total: ActivityPage['total'];
  auctionIds: string[];
};

export function activityPageBoundary(cursor: string | null, page: ActivityPage): ActivityPageBoundary {
  return {cursor, state: page.state, total: page.total, auctionIds: page.items.map(item => item.auction_id.toLowerCase())};
}

export function continuesActivity(trail: ActivityPageBoundary[], page: ActivityPage) {
  if (!trail.length || page.state === 'unavailable') return true;
  if (trail.some(prior => prior.state !== page.state || prior.total !== page.total ||
    (page.next_cursor !== null && page.next_cursor === prior.cursor))) return false;

  const seen = new Set(trail.flatMap(prior => prior.auctionIds));
  if (page.items.some(item => seen.has(item.auction_id.toLowerCase()))) return false;

  const visited = seen.size + page.items.length;
  return page.total !== null && visited <= page.total &&
    (page.next_cursor !== null) === (visited < page.total);
}

export const activityRead=definePageRead<[access:string,view:ActivityView,cursor:string|null,authorizationEpoch?:string],CurrentActivity>({
  key:(access:string,view:ActivityView,cursor:string|null,authorizationEpoch?:string)=>authorizationEpoch
    ?['L16','buyer-activity',access,authorizationEpoch,view,cursor]:['L16','buyer-activity',access,view,cursor],
  fresh:0,warm:'open-only',
  ask:async(signal,access:string,view:ActivityView,cursor:string|null):Promise<CurrentActivity>=>{
    const params=new URLSearchParams({view});
    if(cursor) params.set('cursor',cursor);
    const page=await authenticatedRequest<CurrentActivity>(`/api/web/v1/communications/v1/buyer-workspace?${params}`,{signal,accessFingerprint:access,cache:'no-store'});
    if(!validPage(page,view,cursor)) throw new ApiError(503,'invalid_activity_page','');
    return page;
  },
});
