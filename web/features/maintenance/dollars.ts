import { normalizeDigits } from '@beirut-time/i18n';
export function dollars(value:string):number|null {
  const clean=normalizeDigits(value);
  if(!/^\d{1,10}(\.\d{1,2})?$/.test(clean))return null;
  const [whole,fraction='']=clean.split('.');const cents=Number(whole)*100+Number(fraction.padEnd(2,'0'));
  return cents<=999999999999?cents:null;
}
