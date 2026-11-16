import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { DestinationLink } from '../shell/foundation/destination';
const state=vi.hoisted(()=>({pending:false,shown:false,effected:false,cleanup:undefined as (()=>void)|undefined,anchor:{current:null as HTMLAnchorElement|null}}));
vi.mock('next/link',()=>({default:'a',useLinkStatus:()=>({pending:state.pending})}));
vi.mock('react',async()=>({...await vi.importActual('react'),useSyncExternalStore:(_subscribe:unknown,get:()=>unknown)=>get(),useRef:()=>state.anchor,useState:()=>[state.shown,(value:boolean)=>{state.shown=value;}],useEffect:(run:()=>undefined|(()=>void))=>{if (!state.effected) {state.effected=true;state.cleanup=run() ?? undefined;}}}));
type View=ReactElement<Record<string,unknown>>;
function pendingChild(path:string) {
  const link=DestinationLink({href:'/en/internal/components',label:'Components',icon:'home',path});
  const icon=Children.toArray(link.props.children).find(child=>isValidElement<Record<string,unknown>>(child) && 'path' in child.props) as View;
  return (icon.type as (props:unknown)=>View)(icon.props);
}
function mounted(path:string) {const child=pendingChild(path);return {child,icon:(child.type as (props:unknown)=>View)(child.props)};}
beforeEach(()=>{vi.useFakeTimers();state.pending=false;state.shown=false;state.effected=false;state.cleanup=undefined;const attributes=new Map<string,string>();state.anchor.current={isConnected:true,getAttribute:(key:string)=>attributes.get(key) ?? null,setAttribute:(key:string,value:string)=>{attributes.set(key,value);},removeAttribute:(key:string)=>{attributes.delete(key);}} as unknown as HTMLAnchorElement;vi.stubGlobal('window',{matchMedia:()=>({matches:false})});vi.stubGlobal('document',{documentElement:{}});vi.stubGlobal('getComputedStyle',()=>({getPropertyValue:()=> '120ms'}));});
afterEach(()=>{state.cleanup?.();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
it('the real link branch mounts its delayed icon only while Next is pending and commit cancels that mounted effect',()=>{
  expect(pendingChild('/internal/page').props.pending).not.toBe(true);state.pending=true;expect(mounted('/internal/page').icon.props.pending).toBe(false);vi.advanceTimersByTime(119);expect(mounted('/internal/page').icon.props.pending).toBe(false);expect(state.anchor.current?.getAttribute('aria-busy')).toBeNull();
  state.pending=false;const committed=pendingChild('/internal/page');expect(committed.type).not.toBe(mountedType());state.cleanup?.();vi.advanceTimersByTime(100);expect(state.shown).toBe(false);expect(state.anchor.current?.getAttribute('aria-busy')).toBeNull();
  function mountedType() {state.pending=true;const child=pendingChild('/internal/page');state.pending=false;return child.type;}
});
it('disabled destination links keep their target slot but refuse focus/activation/prefetch',()=>{
  const link=DestinationLink({href:'/en/internal/components',label:'Components',icon:'home',path:'/internal/page',disabled:true}), event={preventDefault:vi.fn(),key:'Enter',currentTarget:{dataset:{}}};expect(link.props['aria-disabled']).toBe(true);expect(link.props.tabIndex).toBe(-1);expect(link.props.prefetch).toBe(false);link.props.onClick!(event as never);link.props.onKeyDown!(event as never);expect(event.preventDefault).toHaveBeenCalledTimes(2);
});
it('a genuinely slow destination gets the same stable glyph after120ms; a committed-path key replaces/cancels an older attempt',()=>{
  state.pending=true;const first=mounted('/internal/page');expect(first.child.key).toBe('/internal/page');vi.advanceTimersByTime(120);expect(mounted('/internal/page').icon.props.pending).toBe(true);expect(state.anchor.current?.getAttribute('aria-busy')).toBe('true');expect(pendingChild('/internal/components').key).toBe('/internal/components');state.cleanup?.();
});
