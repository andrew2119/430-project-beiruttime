import type { Command } from '@contracts/contracts-trust/disputes/v1';
import { normalizeDigits } from '@/lib/i18n';
export function dollars(value:string):number|null {
 const text=normalizeDigits(value).trim();
 if(!/^\d{1,13}(\.\d{1,2})?$/.test(text))return null;
 const [whole,fraction='']=text.split('.');
 const cents=Number(whole)*100+Number(fraction.padEnd(2,'0'));
 return Number.isSafeInteger(cents)&&cents<=9007199254740991?cents:null;
}
export type Draft={reason:string;amount:string;file:File|null;operation:Command|null};
export function freshDraft():Draft {return {reason:'',amount:'',file:null,operation:null};}
