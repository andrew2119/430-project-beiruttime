import { beginThemeIntent } from './theme-intent';
import type { Theme } from './theme';
type Runtime = typeof import('./theme-transition');
/** A cold action changes preference immediately; a later code load never
 * replays that action or supersedes a newer preference. */
export function createThemeRequest(read:()=>Promise<Runtime>) {
  let runtime:Runtime|undefined, pending:Promise<void>|undefined;
  const warm = ()=>pending ??= read().then(module=>{runtime = module;},()=>{pending = undefined;});
  const change = (next:Theme,apply:(value:Theme)=>void,animate:boolean)=>{
    if (animate && runtime) {runtime.changeTheme(next,apply,true);return;}
    const intent = beginThemeIntent();apply(next);intent.release();
  };
  return {warm,change};
}
const request = createThemeRequest(()=>import('./theme-transition'));
export function warmThemeTransition() {if (typeof document !== 'undefined' && 'startViewTransition' in document && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) void request.warm();}
export const requestTheme = request.change;
