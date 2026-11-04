import type { ReservationCommand } from '@contracts/contracts-orders/allocation';
export type PendingReservation={body:ReservationCommand;key:string};
type Memory={owner:string;watch:string;quote:string;checked:string;pending:PendingReservation|null};
let memory:Memory|null=null;
let generation=0;
// Memory-only reconciliation survives locale navigation. Never persisted to browser storage.
export function reservationMemoryEpoch(){return generation;}
export function recallReservation(owner:string){if(memory?.owner!==owner)memory=null;return memory;}
export function rememberReservation(value:Memory,expectedGeneration:number){if(expectedGeneration===generation)memory=value;}
export function purgeReservation(){generation++;memory=null;}
