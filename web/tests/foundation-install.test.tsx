import { afterEach, expect, it, vi } from 'vitest';
import { Button, Popover } from '@beirut-time/ui/foundation';
import { ShellInstall } from '../shell/foundation/install';

const state = vi.hoisted(() => ({canInstall:false,isStandalone:false,isIOS:false,promptInstall:vi.fn()}));
vi.mock('react', async () => ({...await vi.importActual('react'),useState:() => [false,vi.fn()]}));
vi.mock('../shell/install-prompt-provider', () => ({useInstallPrompt:() => state}));
afterEach(() => {state.canInstall=false;state.isStandalone=false;state.isIOS=false;vi.clearAllMocks();});
it('offers only a supported explicit install or the existing manual guidance', () => {
  expect(ShellInstall({locale:'en'})).toBeNull();
  state.canInstall=true;
  const install = ShellInstall({locale:'en'})!;
  expect(install.type).toBe(Button);
  expect(state.promptInstall).not.toHaveBeenCalled();
  install.props.onClick();
  expect(state.promptInstall).toHaveBeenCalledOnce();
  state.canInstall=false;state.isIOS=true;
  const guidance = ShellInstall({locale:'ar'})!;
  expect(guidance.type).toBe(Popover);
  expect(guidance.props.children[1].props.children.props.children).toBeTruthy();
  state.isStandalone=true;
  expect(ShellInstall({locale:'ar'})).toBeNull();
});
