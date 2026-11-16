import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ComponentProps, type MouseEvent, type KeyboardEvent, type PointerEvent, type FocusEvent } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { registrations } from '../registry.generated';
import { NavigationIcon, PendingNavigationIcon, navigationIcons, type NavigationDestination } from '../shell/navigation-icon';
import { ThemeSwitch } from '../shell/theme-switch';

const state = vi.hoisted(() => ({theme:'light' as 'light'|'dark', apply:vi.fn(), transition:vi.fn(), click:undefined as ((detail:number)=>void)|undefined, key:undefined as (()=>void)|undefined, pointer:undefined as (()=>void)|undefined, focus:undefined as (()=>void)|undefined, target:{dataset:{} as Record<string,string>,matches:():boolean=>true}, pending:false}));
vi.mock('next/link', () => ({useLinkStatus:() => ({pending:state.pending})}));
vi.mock('@/shell/theme-provider', () => ({useTheme:() => ({theme:state.theme, applyTheme:state.apply})}));
vi.mock('@/lib/theme-transition', () => ({changeTheme:(theme:string,apply:(theme:string)=>void,animate:boolean) => {state.transition(theme,animate);apply(theme);}}));
vi.mock('@beirut-time/ui', async () => {
  const {createElement:element}=await import('react');
  return {Button:({children,variant,size,onClick,onKeyDown,onPointerDown,onFocus,...props}:ComponentProps<'button'> & {variant?:string;size?:string}) => {
    void variant;void size;
    state.click=detail => onClick?.({detail} as MouseEvent<HTMLButtonElement>);
    state.key=()=>onKeyDown?.({currentTarget:state.target} as unknown as KeyboardEvent<HTMLButtonElement>);
    state.pointer=()=>onPointerDown?.({currentTarget:state.target} as unknown as PointerEvent<HTMLButtonElement>);
    state.focus=()=>onFocus?.({currentTarget:state.target} as unknown as FocusEvent<HTMLButtonElement>);
    return element('button',props,children);
  }};
});
beforeEach(() => {vi.clearAllMocks();state.theme='light';state.pending=false;state.click=undefined;state.key=undefined;state.pointer=undefined;state.focus=undefined;state.target.dataset={};state.target.matches=()=>true;});

describe('navigation motion uses marketplace destinations without moving labels', () => {
  it('covers every registered navigation destination and no unrelated destination', () => {
    const ids=registrations.flatMap(registration => registration.navigation ?? []).map(entry => entry.id);
    expect(Object.keys(navigationIcons).sort()).toEqual([...new Set(ids)].sort());
  });
  it('renders every glyph as decorative and static by default, including active/pending states', () => {
    for (const id of Object.keys(navigationIcons) as NavigationDestination[]) {
      const markup=renderToStaticMarkup(createElement(NavigationIcon,{id,active:true,pending:true}));
      expect(markup).toContain('class="bt-nav-icon"');
      expect(markup).toContain('aria-hidden="true"');
      expect(markup).toMatch(/class="[^"]*\bbt-nav-glyph\b[^"]*"/);
      expect(markup).toContain('data-active=""');
      expect(markup).toContain('data-pending=""');
      expect(markup).not.toContain('data-bt-animate');
    }
  });
  it('only enables explicitly opted-in pointer arrivals, never keyboard motion', () => {
    const pointer=renderToStaticMarkup(createElement(NavigationIcon,{id:'seller-auctions',active:true,input:'pointer',animateArrival:true}));
    expect(pointer).toContain('data-bt-animate="pointer"');
    expect(pointer).toContain('data-motion="strike"');
    const keyboard=renderToStaticMarkup(createElement(NavigationIcon,{id:'seller-auctions',active:true,input:'keyboard',animateArrival:true}));
    expect(keyboard).toContain('data-bt-motion-input="keyboard"');
    expect(keyboard).not.toContain('data-bt-animate');
  });
  it('shares pending and busy states without adding a timer or a changing box', () => {
    state.pending=true;
    expect(renderToStaticMarkup(createElement(PendingNavigationIcon,{id:'watches'}))).toContain('data-pending=""');
    expect(renderToStaticMarkup(createElement(NavigationIcon,{id:'watches',busy:true}))).toContain('data-pending=""');
  });
});

describe('new translated theme switch', () => {
  it('renders an action label and decorative glyph, not a second preference store', () => {
    const markup=renderToStaticMarkup(createElement(ThemeSwitch,{lightLabel:'Use light',darkLabel:'الوضع الداكن'}));
    expect(markup).toContain('aria-label="الوضع الداكن"');
    expect(markup).toContain('type="button"');
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain('bt-theme-switch-glyph');
    state.theme='dark';
    expect(renderToStaticMarkup(createElement(ThemeSwitch,{lightLabel:'Use light',darkLabel:'Use dark'}))).toContain('aria-label="Use light"');
  });
  it('marks keyboard focus/press before CSS feedback and restores pointer mode on a real press', () => {
    renderToStaticMarkup(createElement(ThemeSwitch,{lightLabel:'Use light',darkLabel:'Use dark'}));
    state.focus?.();expect(state.target.dataset.btMotionInput).toBe('keyboard');
    state.pointer?.();expect(state.target.dataset.btMotionInput).toBe('pointer');
    state.target.matches=()=>false;
    state.focus?.();expect(state.target.dataset.btMotionInput).toBe('pointer');
    state.key?.();expect(state.target.dataset.btMotionInput).toBe('keyboard');
  });
  it('keyboard is immediate and rapid pointer requests toggle the desired state, not a stale render', () => {
    renderToStaticMarkup(createElement(ThemeSwitch,{lightLabel:'Use light',darkLabel:'Use dark'}));
    state.click?.(0);
    state.click?.(1);
    expect(state.transition.mock.calls).toEqual([['dark',false],['light',true]]);
    expect(state.apply.mock.calls).toEqual([['dark'],['light']]);
  });
});
