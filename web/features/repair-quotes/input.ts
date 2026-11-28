import { normalizeDigits } from '@beirut-time/i18n';

export function repairMinor(value:string):number {
 const text=normalizeDigits(value).trim();
 if(text.length>20||!/^\d+(?:\.\d{1,2})?$/.test(text))throw new Error('invalidMoney');
 const [whole,fraction='']=text.split('.');
 const minor=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
 if(minor>9_000_000_000_000n)throw new Error('invalidMoney');
 return Number(minor);
}
