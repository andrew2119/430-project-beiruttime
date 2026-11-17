export type DismissSide = 'down'|'left'|'right';
export const DISMISS_DISTANCE = 0.25;
export const DISMISS_VELOCITY = 0.11;
export type TravelSample = {t:number; travel:number};

export function rubberBand(distance:number, size:number): number {return distance <= 0 || size <= 0 ? 0 : (1 - 1 / (distance * 0.55 / size + 1)) * size;}
export function inverseRubberBand(distance:number, size:number): number {const share = Math.min(Math.max(distance / size,0),0.99); return size <= 0 ? 0 : (1 / (1-share) - 1) * size / 0.55;}
export function releaseVelocity(samples:readonly TravelSample[], time:number): number {
  const last = samples.at(-1);
  if (!last) return 0;
  const first = samples.find(sample => sample.t >= time - 100) ?? last;
  return time > first.t ? (last.travel - first.travel) / (time - first.t) : 0;
}
export function shouldDismiss(distance:number, size:number, velocity:number): boolean {return distance > 0 && size > 0 && (distance >= size * DISMISS_DISTANCE || velocity >= DISMISS_VELOCITY);}
export function declaredSide(entrance:string): DismissSide|null {
  const match = /^\s*translate([XY])\(\s*([+-]?(?:\d*\.)?\d+)(?:[a-z%]+)?\s*\)\s*$/i.exec(entrance);
  return !match ? null : match[1].toLowerCase() === 'y' ? 'down' : Number(match[2]) < 0 ? 'left' : Number(match[2]) > 0 ? 'right' : null;
}
export function nearbySide(left:number, right:number, width:number): DismissSide {return left <= 32 && right < width - 32 ? 'left' : right >= width - 32 && left > 32 ? 'right' : 'down';}
export function ownsGesture(panel:Element, target:Element, attached:{has:(element:Element)=>boolean}): boolean {
  for (let node:Element|null = target; node && node !== panel; node = node.parentElement) if (attached.has(node)) return false;
  return panel.contains(target);
}
