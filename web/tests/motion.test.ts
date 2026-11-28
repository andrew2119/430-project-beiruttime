import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { readMotionToken, prefersReducedMotion, markMotionInput } from '@beirut-time/ui/motion';
import { readEasingToken } from '@beirut-time/ui/motion-easing';
import { createRequire } from 'node:module';

const css = readFileSync(new URL('../styles/bt-motion.css', import.meta.url), 'utf8');
const local = createRequire(new URL('../package.json', import.meta.url));
const parse = createRequire(local.resolve('next/package.json'))('postcss');
const roots: Record<string,string> = {};
parse.parse(css).walkDecls((entry:{prop:string;value:string;parent:{selector?:string}}) => {if (entry.parent.selector === ':root') roots[entry.prop]=entry.value;});
let reduced = false;
let values: Record<string, string>;
let attrs: Map<string, string>;
let root: HTMLElement;
let doc: Document;
beforeEach(() => {
  reduced = false;
  values = {...roots, '--ds-motion-fast':'0.15s', '--ds-motion-reduced':'0.001ms'};
  attrs = new Map();
  root = {setAttribute:(name:string,value:string) => attrs.set(name,value), removeAttribute:(name:string) => attrs.delete(name)} as unknown as HTMLElement;
  doc = {documentElement:root} as unknown as Document;
  vi.stubGlobal('document', doc);
  vi.stubGlobal('window', {matchMedia:vi.fn(() => ({matches:reduced}))});
  vi.stubGlobal('getComputedStyle', vi.fn(() => ({getPropertyValue:(name:string) => values[name] ?? ''})));
});
afterEach(() => vi.unstubAllGlobals());

describe('one CSS pacing vocabulary, read at the action', () => {
  it('converts seconds/milliseconds without copying duration values into script', () => {
    expect(readMotionToken('--bt-motion-press')).toBe(130);
    expect(readMotionToken('--bt-motion-overlay')).toBe(250);
    expect(readMotionToken('--ds-motion-fast')).toBe(150);
    values['--bt-motion-fast']='0.2S';
    expect(readMotionToken('--bt-motion-fast')).toBe(200);
    values['--bt-motion-fast']='175ms';
    expect(readMotionToken('--bt-motion-fast',root)).toBe(175);
    expect(getComputedStyle).toHaveBeenLastCalledWith(root);
  });
  it('fails closed on absent, negative, nonfinite, unitless and unreadable values', () => {
    for (const value of ['', '-1ms', 'NaNms', 'Infinitys', '1e999s', '200', 'calc(100ms + 10ms)', 'var(--missing)']) {
      values['--bt-motion-fast']=value;
      expect(readMotionToken('--bt-motion-fast')).toBeUndefined();
    }
    expect(readMotionToken('--missing')).toBeUndefined();
  });
  it('queries current reduction each time; canonical releases land at zero, old reads retain their exact behavior', () => {
    expect(prefersReducedMotion()).toBe(false);
    reduced=true;
    expect(prefersReducedMotion()).toBe(true);
    for (const name of ['press','fast','popover','menu','overlay','exit','image','gentle','theme','icon','pulse']) expect(readMotionToken(`--bt-motion-${name}`)).toBe(0);
    expect(readMotionToken('--ds-motion-fast')).toBe(0.001);
    expect(readMotionToken('--bt-motion-safety')).toBe(5000);
    reduced=false;
    expect(readMotionToken('--bt-motion-fast')).toBe(150);
  });
  it('reads only valid shared curves, never a private ease-in or an unresolved expression', () => {
    expect(readEasingToken('--bt-ease-out')).toBe('cubic-bezier(0.23, 1, 0.32, 1)');
    expect(readEasingToken('--bt-ease-travel')).toBe('cubic-bezier(0.77, 0, 0.175, 1)');
    expect(readEasingToken('--bt-ease-drawer')).toBe('cubic-bezier(0.32, 0.72, 0, 1)');
    expect(readEasingToken('--bt-ease-constant')).toBe('linear');
    for (const value of ['', 'ease-in', 'var(--curve)', 'cubic-bezier(2,0,0,1)', 'cubic-bezier(0,0,-1,1)', 'cubic-bezier(NaN,0,0,1)']) {
      values['--bt-ease-out']=value;
      expect(readEasingToken('--bt-ease-out')).toBeUndefined();
    }
    expect(readEasingToken('--ease-in-hard')).toBeUndefined();
  });
  it('marks discrete pointer and keyboard boundaries without a preference store or frame loop', () => {
    const target={dataset:{}} as HTMLElement;
    markMotionInput(target,'keyboard');expect(target.dataset.btMotionInput).toBe('keyboard');
    markMotionInput(target,'pointer');expect(target.dataset.btMotionInput).toBe('pointer');
  });
  it('is safe during a server render and with no media-query API', () => {
    vi.stubGlobal('window',undefined);
    expect(readMotionToken('--bt-motion-fast')).toBeUndefined();
    expect(readEasingToken('--bt-ease-out')).toBeUndefined();
    expect(prefersReducedMotion()).toBe(false);
    vi.stubGlobal('window',{});
    expect(prefersReducedMotion()).toBe(false);
    expect(readMotionToken('--bt-motion-fast')).toBe(150);
  });
});

function pendingTransition() {
  let finish!: () => void;
  let reject!: (reason?:unknown) => void;
  const finished = new Promise<void>((resolve,fail) => {finish=resolve;reject=fail;});
  return {finished, finish, reject, skipTransition:vi.fn()};
}
describe('new theme transition entry point', () => {
  beforeEach(() => vi.resetModules());
  it('commits keyboard, reduced, unsupported and unreadable-token changes immediately', async () => {
    const {changeTheme}=await import('../lib/theme-transition');
    const apply=vi.fn();
    changeTheme('dark',apply,false);
    expect(apply).toHaveBeenLastCalledWith('dark');
    expect(attrs.has('data-bt-theme-transition')).toBe(false);
    const start=vi.fn();
    Object.assign(doc,{startViewTransition:start});
    reduced=true;
    changeTheme('light',apply,true);
    expect(start).not.toHaveBeenCalled();
    reduced=false;
    values['--bt-motion-theme']='var(--missing)';
    changeTheme('dark',apply,true);
    expect(start).not.toHaveBeenCalled();
    expect(apply).toHaveBeenCalledTimes(3);
  });
  it('marks only its own snapshot and clears the marker when finished', async () => {
    const {changeTheme}=await import('../lib/theme-transition');
    const transition=pendingTransition(), apply=vi.fn();
    Object.assign(doc,{startViewTransition:vi.fn((update:()=>void) => {update();return transition;})});
    changeTheme('dark',apply,true);
    expect(apply).toHaveBeenCalledExactlyOnceWith('dark');
    expect(attrs.has('data-bt-theme-transition')).toBe(true);
    transition.finish();
    await transition.finished; await Promise.resolve(); await Promise.resolve();
    expect(attrs.has('data-bt-theme-transition')).toBe(false);
  });
  it('cancels old snapshots and ignores late old callbacks without clearing a newer marker', async () => {
    const {changeTheme}=await import('../lib/theme-transition');
    const callbacks: Array<()=>void>=[], first=pendingTransition(), second=pendingTransition(), apply=vi.fn();
    Object.assign(doc,{startViewTransition:vi.fn((update:()=>void) => {callbacks.push(update);return callbacks.length===1?first:second;})});
    changeTheme('dark',apply,true);
    changeTheme('light',apply,true);
    expect(first.skipTransition).toHaveBeenCalledOnce();
    callbacks[0]();callbacks[1]();
    expect(apply).toHaveBeenCalledExactlyOnceWith('light');
    first.finish();await first.finished;await Promise.resolve();await Promise.resolve();
    expect(attrs.has('data-bt-theme-transition')).toBe(true);
    second.finish();await second.finished;await Promise.resolve();await Promise.resolve();
    expect(attrs.has('data-bt-theme-transition')).toBe(false);
  });
  it('a keyboard interruption lands immediately and a rejected snapshot is handled', async () => {
    const {changeTheme}=await import('../lib/theme-transition');
    const transition=pendingTransition(), apply=vi.fn();
    let stale!:()=>void;
    Object.assign(doc,{startViewTransition:vi.fn((update:()=>void) => {stale=update;return transition;})});
    changeTheme('dark',apply,true);
    changeTheme('light',apply,false);
    stale();
    expect(apply).toHaveBeenCalledExactlyOnceWith('light');
    expect(attrs.has('data-bt-theme-transition')).toBe(false);
    transition.reject(new Error('cancelled'));
    await transition.finished.catch(()=>{});await Promise.resolve();await Promise.resolve();
  });
  it('a failed snapshot API never prevents the preference from changing', async () => {
    const {changeTheme}=await import('../lib/theme-transition');
    const apply=vi.fn();
    Object.assign(doc,{startViewTransition:vi.fn(() => {throw new Error('unavailable');})});
    changeTheme('dark',apply,true);
    expect(apply).toHaveBeenCalledExactlyOnceWith('dark');
    expect(attrs.has('data-bt-theme-transition')).toBe(false);
  });
});

