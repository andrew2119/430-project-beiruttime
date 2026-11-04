'use client';
import { authenticatedRequest } from '@/features/identity/session';
import { request } from '@/lib/api/client';
import type { Availability, AllocationOperation, Order, ReservationCommand } from '@contracts/contracts-orders/allocation';
const root='/api/web/v1/orders/v1';
export const buyNowApi={
  availability:(id:string,signal?:AbortSignal)=>request<Availability>(`${root}/watches/${encodeURIComponent(id)}/availability`,{signal}),
  listingAvailability:(id:string,signal?:AbortSignal)=>request<Availability>(`${root}/listings/${encodeURIComponent(id)}/availability`,{signal}),
  reserve:(body:ReservationCommand,key:string)=>authenticatedRequest<AllocationOperation>(`${root}/reservations`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)}),
  orders:(signal?:AbortSignal)=>authenticatedRequest<{items:Order[]}>(`${root}/orders`,{signal}),
  order:(id:string,signal?:AbortSignal,organization:string|null=null)=>authenticatedRequest<{order:Order;history:{action:string;reason:string;revision:number;occurred_at:string}[]}>(`${root}/orders/${encodeURIComponent(id)}${organization?'?organization_id='+encodeURIComponent(organization):''}`,{signal}),
};
