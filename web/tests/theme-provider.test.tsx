import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { ThemeProvider, useTheme } from '../shell/theme-provider';
import { changeTheme } from '../lib/theme-transition';
/* eslint react-hooks/globals: "error" */

const css=readFileSync(new URL('../styles/bt-motion.css',import.meta.url),'utf8');
let controls: ReturnType<typeof useTheme>;
let root: HTMLElement;
let attrs: Map<string,string>;
let callbacks: Array<()=>void>;
let frames: Array<{finish:()=>void;finished:Promise<void>;skipTransition:ReturnType<typeof vi.fn>}>;
// eslint-disable-next-line react-hooks/globals -- SSR-only probe captures handlers for after-render unit assertions.
function Capture() {controls=useTheme();return null;}
beforeEach(() => {
  attrs=new Map();callbacks=[];frames=[];
  root={dataset:{theme:'light'},setAttribute:(name:string,value:string)=>attrs.set(name,value),removeAttribute:(name:string)=>attrs.delete(name)} as unknown as HTMLElement;
  vi.stubGlobal('document',{documentElement:root,startViewTransition:(update:()=>void)=>{
    callbacks.push(update);
    let finish!:()=>void;
    const finished=new Promise<void>(resolve=>{finish=resolve;});
    const frame={finished,finish,skipTransition:vi.fn()};frames.push(frame);return frame;
  }});
  vi.stubGlobal('window',{matchMedia:()=>({matches:false})});
  vi.stubGlobal('getComputedStyle',()=>({getPropertyValue:(name:string)=>css.match(new RegExp(`${name}:\\s*([^;]+)`))?.[1]??''}));
  renderToStaticMarkup(<ThemeProvider initialTheme="light"><Capture/></ThemeProvider>);
});
afterEach(async () => {
  for (const frame of frames) frame.finish();
  await Promise.all(frames.map(frame=>frame.finished));await Promise.resolve();await Promise.resolve();
  vi.unstubAllGlobals();
});

it('the existing control still uses its old unmarked snapshot path and applies its same target', () => {
  controls.cycleTheme();
  expect(callbacks).toHaveLength(1);
  expect(attrs.has('data-bt-theme-transition')).toBe(false);
  callbacks[0]();
  expect(root.dataset.theme).toBe('dark');
});
it('a canonical keyboard request cancels an old snapshot and prevents its late callback from winning', () => {
  controls.cycleTheme();
  changeTheme('light',controls.applyTheme,false);
  expect(frames[0].skipTransition).toHaveBeenCalledOnce();
  callbacks[0]();
  expect(root.dataset.theme).toBe('light');
  expect(attrs.has('data-bt-theme-transition')).toBe(false);
});
it('an old control supersedes a canonical request, removes its marker and rejects its stale callback', () => {
  changeTheme('light',controls.applyTheme,true);
  expect(attrs.has('data-bt-theme-transition')).toBe(true);
  controls.cycleTheme();
  expect(frames[0].skipTransition).toHaveBeenCalledOnce();
  expect(attrs.has('data-bt-theme-transition')).toBe(false);
  callbacks[1]();callbacks[0]();
  expect(root.dataset.theme).toBe('dark');
});
