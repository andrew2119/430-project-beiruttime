import { readMotionToken } from '../motion-tokens';
import type { ListKey, RowPhase } from './list-model';

type Point = {x:number; y:number};
export function matrixTranslation(value:string):Point {
  const match = /^matrix(3d)?\(([^)]+)\)$/.exec(value);
  if (!match) return {x:0,y:0};
  const parts = match[2].split(',').map(Number), at = match[1] ? 12 : 4;
  return parts.length === (match[1] ? 16 : 6) && parts.every(Number.isFinite) ? {x:parts[at],y:parts[at+1]} : {x:0,y:0};
}
function translate(node:HTMLElement,x:number,y:number) {node.style.transform = `translate(${x}px, ${y}px)`;}
function opacity(node:HTMLElement,value:number) {node.style.opacity = String(value);}
function removeFlags(node:HTMLElement) {for (const flag of ['data-enter','data-exit','data-resume','data-reorder']) node.removeAttribute(flag);}
function natural(node:HTMLElement) {removeFlags(node);node.style.removeProperty('transform');node.style.removeProperty('opacity');node.style.removeProperty('transition');}
function capture(node:HTMLElement) {for (const animation of node.getAnimations()) {try {animation.commitStyles();animation.cancel();} catch {animation.cancel();}}}

type Running = {phase:RowPhase; cancel:()=>void};
/** One read batch, one layout flush, one write batch. Rapid reversals start
 * from computed visual state, never from a restarted entrance keyframe. */
export function createRowBatch() {
  const running = new Map<ListKey,Running>(), previous = new Map<ListKey,Point>();
  let oldOrder = '', oldWidth = 0;
  const remove = (key:ListKey) => {running.get(key)?.cancel();running.delete(key);previous.delete(key);};
  const update = (root:HTMLElement,nodes:ReadonlyMap<ListKey,HTMLElement>,order:readonly ListKey[],phases:ReadonlyMap<ListKey,RowPhase>,atomic:boolean,finish:(key:ListKey)=>void) => {
    const origin = root.getBoundingClientRect(), signature = JSON.stringify(order);
    const reorder = !atomic && !!oldOrder && signature !== oldOrder && Math.abs(oldWidth-origin.width) < 1;
    const reads = order.flatMap(key=>{
      const node = nodes.get(key);if (!node) return [];
      const box = node.getBoundingClientRect(), css = getComputedStyle(node), shift = matrixTranslation(css.transform), shown = Number.parseFloat(css.opacity);
      return [{key,node,phase:phases.get(key) ?? 'steady' as RowPhase,shift,shown:Number.isFinite(shown) ? shown : 1,target:{x:box.left-origin.left-shift.x,y:box.top-origin.top-shift.y}}];
    });
    const release:Array<()=>void> = [];
    for (const row of reads) {
      const before = previous.get(row.key), current = running.get(row.key);
      const dx = reorder && before ? before.x+row.shift.x-row.target.x : row.shift.x, dy = reorder && before ? before.y+row.shift.y-row.target.y : row.shift.y;
      const moved = reorder && before && (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5);
      previous.set(row.key,row.target);
      if (atomic) {current?.cancel();capture(row.node);natural(row.node);running.set(row.key,{phase:'steady',cancel:()=>{}});continue;}
      if (current?.phase === row.phase && !moved) continue;
      current?.cancel();
      if (row.phase === 'enter' && !current && !before) {
        removeFlags(row.node);row.node.setAttribute('data-enter','');
        const end = (event:AnimationEvent)=>{if (event.target === row.node && event.animationName === 'bt-row-in') {cancel();natural(row.node);}};
        const duration = readMotionToken('--bt-motion-image',row.node) ?? 0;
        const timer = window.setTimeout(()=>{cancel();natural(row.node);},duration*2);
        const cancel = ()=>{window.clearTimeout(timer);row.node.removeEventListener('animationend',end);};
        row.node.addEventListener('animationend',end);running.set(row.key,{phase:row.phase,cancel});continue;
      }
      capture(row.node);row.node.style.transition = 'none';removeFlags(row.node);translate(row.node,dx,dy);opacity(row.node,row.shown);
      row.node.setAttribute(row.phase === 'exit' ? 'data-exit' : moved ? 'data-reorder' : 'data-resume','');
      let active = true, timer:number|undefined;
      const cancel = ()=>{active = false;if (timer !== undefined) window.clearTimeout(timer);row.node.removeEventListener('transitionend',end);};
      const complete = ()=>{if (!active) return;cancel();if (row.phase === 'exit') finish(row.key);else natural(row.node);};
      const end = (event:TransitionEvent)=>{
        if (event.target !== row.node || !['opacity','transform'].includes(event.propertyName)) return;
        const css = getComputedStyle(row.node), shown = Number.parseFloat(css.opacity), shift = matrixTranslation(css.transform);
        if (row.phase === 'exit' ? event.propertyName === 'opacity' && shown <= 0.001 : shown >= 0.999 && Math.abs(shift.x) < 0.5 && Math.abs(shift.y) < 0.5) complete();
      };
      row.node.addEventListener('transitionend',end);running.set(row.key,{phase:row.phase,cancel});
      release.push(()=>{
        row.node.style.removeProperty('transition');row.node.style.removeProperty('opacity');
        if (row.phase !== 'exit') row.node.style.removeProperty('transform');
        const duration = readMotionToken(row.phase === 'exit' ? '--bt-motion-exit' : '--bt-motion-popover',row.node) ?? 0;
        if (duration === 0) complete();else timer = window.setTimeout(complete,duration*2);
      });
    }
    if (release.length) {void root.offsetWidth;for (const run of release) run();}
    for (const key of [...running.keys()]) if (!nodes.has(key)) remove(key);
    oldOrder = signature;oldWidth = origin.width;
  };
  const measure = (root:HTMLElement,nodes:ReadonlyMap<ListKey,HTMLElement>) => {
    const origin = root.getBoundingClientRect();
    for (const [key,node] of nodes) {const rect = node.getBoundingClientRect(), shift = matrixTranslation(getComputedStyle(node).transform);previous.set(key,{x:rect.left-origin.left-shift.x,y:rect.top-origin.top-shift.y});}
    oldWidth = origin.width;
  };
  return {update,measure,remove,dispose:()=>{for (const state of running.values()) state.cancel();running.clear();previous.clear();}};
}
