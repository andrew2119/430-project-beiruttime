export type SaleMode = 'fixed' | 'auction' | 'seller_base';
export type Availability = { watch_id: string; listing_id: string; sale_mode: SaleMode; status: 'available'|'reserved'|'fenced'|'editing'|'withdrawn'; revision: number; is_demo?:boolean };
export type ReservationCommand = { watch_id: string; quote_id: string; expected_revision: number };
export type Order = { id: string; watch_id: string; listing_id?:string; quote_id:string; is_demo?:boolean; buyer_id: string; seller_id: string; organization_id: string|null; state: 'awaiting_payment'|'payment_unknown'|'expired_fenced'|'paid_held'; revision: number; currency: 'USD'|'LBP'; total_minor: number; deadline: string; payment_authority: false };
export type BuyerReservation = {reservation_id:string;listing_id:string;buyer_id:string;state:'awaiting_payment';total_minor:number;currency:'USD'|'LBP';revision:number;expires_at:string;is_demo:boolean};
export type CustodyReceipt = {id:string;order_id:string;organization_id:string;received_at:string;revision:number;valid:true};
export type AllocationOperation = { id: string; request_id: string; status: 'succeeded'|'denied'|'unavailable'|'pending'; resource_id?: string; code?: string; payment_authority?:false; order?: Order };
