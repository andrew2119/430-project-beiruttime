import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { Avatar, Button, Sheet, SheetContent } from '@beirut-time/ui/foundation';
import { FoundationShell } from '../shell/foundation/shell';
import { ShellProfile } from '../shell/foundation/profile';
import { PageReadProvider } from '../lib/page-speed/provider';
import { ShellNavigation } from '../shell/foundation/navigation';
import { DestinationLink } from '../shell/foundation/destination';
import { NAMES, TEXT } from './fixtures/worst-case';
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
it('ordinary drawer close/Escape returns focus through the shared primitive, not a blanket prevention',()=>{
  change(draw(),true);expect(sheet(draw()).props.open).toBe(true);change(draw(),false);const view=draw();expect(sheet(view).props.open).toBe(false);expect(closeFocus(view).preventDefault).not.toHaveBeenCalled();
});
it('a committed new route suppresses the old drawer trigger restoration',()=>{
  change(draw(),true);const view=draw('/internal/components');expect(sheet(view).props.open).toBe(false);expect(closeFocus(view).preventDefault).toHaveBeenCalledOnce();
});
it('unmodified navigation closes the real drawer and leaves destination focus to routing',()=>{
  class Anchor {closest(){return this;}}vi.stubGlobal('Element',Anchor);change(draw(),true);const container=elements(draw()).find(node=>node.props.className === 'bt-shell-drawer-content')!;
  (container.props.onClickCapture as (event:unknown)=>void)({target:new Anchor(),button:0,metaKey:false,ctrlKey:false,shiftKey:false,altKey:false});expect(sheet(draw()).props.open).toBe(false);expect(closeFocus(draw()).preventDefault).toHaveBeenCalledOnce();
});
it('modified/new-tab navigation leaves the drawer open',()=>{
  class Anchor {closest(){return this;}}vi.stubGlobal('Element',Anchor);change(draw(),true);const container=elements(draw()).find(node=>node.props.className === 'bt-shell-drawer-content')!;
  (container.props.onClickCapture as (event:unknown)=>void)({target:new Anchor(),button:0,metaKey:true});expect(sheet(draw()).props.open).toBe(true);
});
it('identity-scoped page replacement never remounts profile revocation state or shell chrome',()=>{
  const view=draw(), scope=elements(view).find(node=>node.type === PageReadProvider)!;expect(scope).toBeDefined();expect(elements(scope).some(node=>node.type === ShellProfile)).toBe(false);expect(elements(scope).some(node=>node.type === 'main')).toBe(true);expect(elements(scope).some(node=>node.props.className === 'bt-shell')).toBe(false);
});
it('real profile/navigation props receive schema-limit, Arabic, emoji, whitespace and expanded-label cases without inventing identity',()=>{
  for (const name of [NAMES.accountAtLimit,NAMES.arabic,NAMES.emojiOnly,NAMES.spaces,'','   ']) {state.slots=[];state.session={account:{display_name:name}};const view=render(()=>ShellProfile({locale:'en',path:'/internal/page'})), avatar=elements(view).find(node=>node.type === Avatar)!;expect(avatar.props.name).toBe(name.trim() ? name : 'Account');expect(avatar.props.label).toBe(avatar.props.name);}
  const view=render(()=>ShellNavigation({entries:[{id:'home',href:'',label:{en:TEXT.expandedLabel,ar:TEXT.expandedLabel},order:0,area:'storefront',roles:['public']}],locale:'ar',path:'/internal/page'}));expect(elements(view).find(node=>node.type === DestinationLink)?.props.label).toBe(TEXT.expandedLabel);
});
it('the real profile holds its pending target and offers revocation retry after local session clearing',async()=>{
  state.session={account:{display_name:'نور الهدى عبد الرحمن'}};let fail!:(reason:Error)=>void;signOut.mockImplementationOnce(()=>{state.session=null;return new Promise((_resolve,reject)=>{fail=reject;});}).mockResolvedValueOnce(undefined);
  const profile=()=>render(()=>ShellProfile({locale:'en',path:'/internal/page'})), action=()=>elements(profile()).find(node=>node.type === Button && node.props.children === 'Sign out')!;
  const request=(action().props.onClick as ()=>Promise<void>)();expect(action()).toBeDefined();expect(action().props.busy).toBe(true);fail(new Error('offline'));await request;expect(action().props.busy).toBe(false);expect(action()).toBeDefined();await (action().props.onClick as ()=>Promise<void>)();expect(action()).toBeUndefined();expect(signOut).toHaveBeenCalledTimes(2);
});
