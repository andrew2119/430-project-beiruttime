/** Retry installation access without retaining a failed or partial identity. */
export function initializeDevice(read:()=>string):{device:string;state:'ready'}|{device:null;state:'unavailable'} {
  try {return {device:read(),state:'ready'};}
  catch {return {device:null,state:'unavailable'};}
}
