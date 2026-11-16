'use client';

import { useEffect, useRef } from 'react';
import { flushSync } from 'react-dom';
import { Moon, Sun } from 'lucide-react';
import { Button } from '@beirut-time/ui';
import { markMotionInput } from '@beirut-time/ui/motion';
import { changeTheme } from '@/lib/theme-transition';
import { nextTheme } from '@/lib/theme';
import { useTheme } from './theme-provider';

/** Translated action labels are required; the icon is decorative. This is not
 * mounted by existing preference controls until their shared composition moves. */
export function ThemeSwitch({lightLabel, darkLabel}: {lightLabel:string; darkLabel:string}) {
  const {theme, applyTheme} = useTheme();
  const desired = useRef(theme);
  useEffect(() => { desired.current = theme; }, [theme]);
  const Icon = theme === 'light' ? Moon : Sun;
  return <Button type="button" variant="ghost" size="icon" className="bt-theme-switch" data-bt-motion-input="none" aria-label={theme === 'light' ? darkLabel : lightLabel}
    onKeyDown={event => markMotionInput(event.currentTarget, 'keyboard')}
    onPointerDown={event => markMotionInput(event.currentTarget, 'pointer')}
    onFocus={event => { if (event.currentTarget.matches(':focus-visible')) markMotionInput(event.currentTarget, 'keyboard'); }}
    onClick={event => {
    const next = nextTheme(desired.current);
    desired.current = next;
    changeTheme(next, value => flushSync(() => applyTheme(value)), event.detail > 0);
  }}><Icon className="bt-theme-switch-glyph" aria-hidden="true" /></Button>;
}
