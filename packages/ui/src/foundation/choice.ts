/** Roving focus skips disabled choices and follows the visual reading direction. */
export function nextChoice(disabled:readonly boolean[], current:number, key:string, rtl:boolean): number {
  const usable = disabled.flatMap((off,index) => off ? [] : [index]);
  if (!usable.length) return -1;
  if (key === 'Home') return usable[0];
  if (key === 'End') return usable[usable.length - 1];
  const step = key === 'ArrowDown' || (key === 'ArrowRight' && !rtl) || (key === 'ArrowLeft' && rtl) ? 1 : -1;
  const index = usable.indexOf(current);
  return usable[(index + step + usable.length) % usable.length];
}
