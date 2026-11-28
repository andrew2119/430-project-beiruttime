import { describe, expect, it, vi } from 'vitest';
import { createThemeRequest } from '../lib/theme-request';
import { beginThemeIntent } from '../lib/theme-intent';
import type { changeTheme } from '../lib/theme-transition';
describe('optional theme snapshots do not enlarge or delay the first control frame',()=>{
  it('keyboard/cold actions commit immediately without a module request or later replay',async()=>{
    let resolve!:(module:{changeTheme:typeof changeTheme})=>void;const read = vi.fn(()=>new Promise<{changeTheme:typeof changeTheme}>(done=>{resolve = done;})), request = createThemeRequest(read), apply = vi.fn();
    request.change('dark',apply,false);request.change('light',apply,true);expect(read).not.toHaveBeenCalled();expect(apply.mock.calls).toEqual([['dark'],['light']]);
    const first = request.warm(), second = request.warm();expect(first).toBe(second);expect(read).toHaveBeenCalledOnce();request.change('dark',apply,true);const animate = vi.fn();resolve({changeTheme:animate});await first;expect(animate).not.toHaveBeenCalled();expect(apply).toHaveBeenCalledTimes(3);
  });
  it('only a later warm pointer action delegates to snapshot/token code; keyboard stays immediate',async()=>{
    const animate = vi.fn(), request = createThemeRequest(async()=>({changeTheme:animate})), apply = vi.fn();await request.warm();request.change('dark',apply,true);expect(animate).toHaveBeenCalledExactlyOnceWith('dark',apply,true);request.change('light',apply,false);expect(apply).toHaveBeenCalledExactlyOnceWith('light');
  });
  it('failed optional code keeps ordinary preference changes usable and permits retry',async()=>{
    const read = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({changeTheme:vi.fn()}), request = createThemeRequest(read), apply = vi.fn();await request.warm();request.change('dark',apply,true);expect(apply).toHaveBeenCalledExactlyOnceWith('dark');await request.warm();expect(read).toHaveBeenCalledTimes(2);
  });
  it('a cold/keyboard request supersedes an old preference snapshot before applying its target',()=>{
    const cancel = vi.fn(), old = beginThemeIntent(cancel), apply = vi.fn(), request = createThemeRequest(vi.fn());request.change('dark',apply,false);expect(cancel).toHaveBeenCalledOnce();expect(old.isCurrent()).toBe(false);expect(apply).toHaveBeenCalledExactlyOnceWith('dark');
  });
});
