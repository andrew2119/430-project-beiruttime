'use client';
import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import {stripLocale} from './paths';
// A language-only address change must not reset focus or scroll.
export function RouteFocus() {
  const path = stripLocale(usePathname());
  const previous = useRef(path);
  useEffect(() => {
    if (previous.current !== path) {
      previous.current = path;
      const target = document.getElementById('main-content');
      target?.focus({ preventScroll: true });
      target?.scrollTo({ top: 0, behavior: 'instant' });
    }
  }, [path]);
  return null;
}
