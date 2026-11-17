import { afterEach, expect, it, vi } from 'vitest';
import { ShellBoundary } from '../shell/shell-boundary';
import { clearPageReadMemory } from '../lib/page-speed/memory';

const state = vi.hoisted(() => ({revision:0, locale:'en', effect:undefined as undefined | (() => () => void)}));
vi.mock('react', async () => ({...await vi.importActual('react'),
  useState:() => [state.revision, (update:(value:number)=>number) => {state.revision = update(state.revision);}],
  useEffect:(effect:() => () => void) => {state.effect = effect;},
  useSyncExternalStore:(_subscribe:unknown, get:() => string) => get(),
}));
vi.mock('next/navigation', () => ({usePathname:() => `/${state.locale}/settings`}));
vi.mock('../shell/locale-context', () => ({useLocale:() => state.locale}));
vi.mock('../lib/page-speed/memory', () => ({clearPageReadMemory:vi.fn(), rememberPageInput:vi.fn()}));
afterEach(() => {vi.unstubAllGlobals(); vi.clearAllMocks(); state.revision = 0; state.locale = 'en';});

it('locale keeps form identity while access events invalidate and replace only the read subtree', () => {
  const listeners = new Map<string, () => void>();
  vi.stubGlobal('window', {addEventListener:(name:string, run:() => void) => listeners.set(name, run), removeEventListener:(name:string) => listeners.delete(name)});
  vi.stubGlobal('document', {addEventListener:vi.fn(), removeEventListener:vi.fn()});
  const children = <form data-operation="operation-17"><input type="password"/><input type="file"/></form>;
  const draw = () => ShellBoundary({serverPath:'/en/settings', children, locale:'en', entries:[]});
  const first = draw(), cleanup = state.effect!();
  state.locale = 'ar';
  const translated = draw();
  expect(translated.type).toBe(first.type);
  expect(translated.key).toBe(first.key);
  expect(translated.props.children).toBe(children);
  expect(translated.props.path).toBe(first.props.path);
  expect(translated.props.accessRevision).toBe(first.props.accessRevision);
  expect(clearPageReadMemory).not.toHaveBeenCalled();
  listeners.get('bt:access-change')!();
  expect(clearPageReadMemory).toHaveBeenCalledOnce();
  expect(draw().props.accessRevision).toBe(1);
  expect(draw().props.children).toBe(children);
  cleanup(); expect(listeners.size).toBe(0);
});
