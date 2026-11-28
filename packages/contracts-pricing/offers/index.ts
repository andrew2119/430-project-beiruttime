import type { Quote } from '../quotes';
export type Offer = {id:string;listing_id:string;listing_revision:number;revision:number;buyer_id:string;seller_id:string;organization_id:string|null;state:'open'|'acceptance_pending'|'accepted'|'rejected'|'expired'|'closed'|'lost';expires_at:string;quote:Quote;order_id:string|null;party?:'buyer'|'seller'};
export type OfferOutcome = {operation_id?:string;status:'succeeded'|'denied'|'pending';code?:string;offer:Offer};
