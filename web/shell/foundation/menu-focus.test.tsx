import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { Sheet, SheetContent } from '@beirut-time/ui/foundation';
import { FoundationShell } from './shell';
const state = vi.hoisted(()=>({slots:[] as unknown[],cursor:0,session:null as unknown,phone:true}));
const signOut = vi.hoisted(()=>vi.fn());
vi.mock('react',async()=>({...await vi.importActual('react'),useEffect:()=>{},useCallback:(fn:unknown)=>fn,useSyncExternalStore:(_subscribe:unknown,get:()=>unknown)=>get(),useRef:(initial:unknown)=>{const at=state.cursor++;if (!(at in state.slots)) state.slots[at]={current:initial};return state.slots[at];},useState:(initial:unknown)=>{const at=state.cursor++;if (!(at in state.slots)) state.slots[at]=initial;return [state.slots[at],(next:unknown)=>{state.slots[at]=typeof next === 'function' ? next(state.slots[at]) : next;}];}}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session,useSessionState:()=>state.session ? 'authenticated' : 'signed-out',refreshSession:vi.fn(),signOut}));
vi.mock('@beirut-time/ui/foundation',async()=>({...await vi.importActual('@beirut-time/ui/foundation'),toast:{error:vi.fn()}}));
vi.mock('next/dynamic',()=>({default:()=>()=>null}));
type View=ReactElement<Record<string,unknown>>;
function elements(view:unknown):View[] {if (!isValidElement(view)) return [];const node=view as View;return [node,...Children.toArray(node.props.children as never).flatMap(elements)];}
function render(run:()=>unknown) {state.cursor=0;return run() as View;}
const draw=(path='/internal/page')=>render(()=>FoundationShell({locale:'en',entries:[],path,children:'Content'}));
function sheet(view:View) {return elements(view).find(node=>node.type === Sheet)!;}
function closeFocus(view:View) {const event={preventDefault:vi.fn()};(elements(view).find(node=>node.type === SheetContent)!.props.onCloseAutoFocus as (event:unknown)=>void)(event);return event;}
function change(view:View,open:boolean) {(sheet(view).props.onOpenChange as (open:boolean)=>void)(open);}
beforeEach(()=>{state.slots=[];state.cursor=0;state.session=null;state.phone=true;signOut.mockReset();vi.stubGlobal('window',{matchMedia:()=>({matches:state.phone})});vi.stubGlobal('navigator',{onLine:true});});
afterEach(()=>vi.unstubAllGlobals());
it.each(['en','ar'] as const)('Escape returns the phone menu to its opening control in %s',locale=>{
  const active = {current:null as unknown};
  const trigger = {isConnected:true,focus:vi.fn(()=>{active.current=trigger;})};
  const drawMenu = (path='/internal/page')=>render(()=>FoundationShell({locale,entries:[],path,children:'Content'}));
  const initial=drawMenu();
  const header=elements(initial).find(node=>node.type === 'header')!;
  (header.props.ref as {current:unknown}).current={querySelector:()=>trigger};
  change(initial,true);
  let view=drawMenu();expect(sheet(view).props.open).toBe(true);
  // Touch activation need not focus the opening control.
  expect(active.current).toBeNull();
  (elements(view).find(node=>node.type === SheetContent)!.props.onEscapeKeyDown as (event:unknown)=>void)({key:'Escape'});
  change(view,false);view=drawMenu();
  expect(sheet(view).props.open).toBe(false);
  expect(closeFocus(view).preventDefault).toHaveBeenCalledOnce();
  expect(active.current).toBe(trigger);
  expect(trigger.focus).toHaveBeenCalledWith({preventScroll:true});
});
it('navigation still suppresses trigger restoration after Escape',()=>{
  const trigger={isConnected:true,focus:vi.fn()}, initial=draw();
  const header=elements(initial).find(node=>node.type === 'header')!;
  (header.props.ref as {current:unknown}).current={querySelector:()=>trigger};
  change(initial,true);
  (elements(draw()).find(node=>node.type === SheetContent)!.props.onEscapeKeyDown as ()=>void)();
  const view=draw('/internal/components');
  expect(closeFocus(view).preventDefault).toHaveBeenCalledOnce();
  expect(trigger.focus).not.toHaveBeenCalled();
});
