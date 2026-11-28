import type {FinancialReadiness} from '../../../../packages/contracts-orders/payments';

/** Synthetic current funds read; never inferred from a historical order state. */
export function financialReadinessFixture(orderId:string,heldMinor=0):FinancialReadiness {
  return {schema_version:3,order_id:orderId,revision:1,
    state:heldMinor>0?'paid_held':'unpaid',held_minor:heldMinor,reserved_minor:0,
    movement_status:'none',currency:'USD',simulated:true,payment_authority:false};
}
