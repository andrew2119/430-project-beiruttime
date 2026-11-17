export type FrameAnswer = {src:string;state:'ready'|'error';instant?:boolean};
/** Resolution belongs to the still-mounted pixel element, not its old URL. */
export async function decodeFrame(image:HTMLImageElement,src:string,instant:boolean,current:()=>boolean,settle:(answer:FrameAnswer)=>void) {
  try {await image.decode();if (current()) settle(image.naturalWidth > 0 ? {src,state:'ready',instant} : {src,state:'error'});}
  catch {if (current()) settle({src,state:'error'});}
}
