export function millimeters(raw:string, unit:'cm'|'mm'):number|null {
  if(raw.length>32) return null;
  const normalized=raw.trim().replace(/[٠-٩۰-۹]/g,digit=>String('٠١٢٣٤٥٦٧٨٩'.includes(digit)?'٠١٢٣٤٥٦٧٨٩'.indexOf(digit):'۰۱۲۳۴۵۶۷۸۹'.indexOf(digit))).replace(/٫/g,'.');
  const match=/^([0-9]{1,3})(?:\.([0-9]))?\s*(cm|mm|سم|مم)?$/.exec(normalized);
  if(!match || (match[3] && !(unit==='cm'?['cm','سم']:['mm','مم']).includes(match[3]))) return null;
  const tenths=Number(match[1])*10+Number(match[2]??0);
  const mm=unit==='cm'?tenths:tenths/10;
  return Number.isInteger(mm)&&mm>=80&&mm<=300?mm:null;
}

export type MeasurementStatus = 'loading'|'ready'|'saving'|'pending'|'saved'|'invalid'|'denied'|'unavailable'|'stale'|'error';

export function refreshedStatus(current:MeasurementStatus, outcome:'verified'|'unavailable'|'denied'):MeasurementStatus {
  if(outcome==='denied') return 'denied';
  if(current==='pending'||current==='saving'||current==='denied') return current;
  if(outcome==='unavailable') return 'unavailable';
  return ['loading','unavailable','stale','error'].includes(current)?'ready':current;
}

/** Revocation lasts for this mounted access partition, including late responses. */
export function createReadFence() {
  let revoked=false;
  return {
    revoke:()=>{revoked=true;},
    accepts:()=>!revoked,
  };
}
