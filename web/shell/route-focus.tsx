'use client';
import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
// Routing owns destination focus, without stealing first-page input focus.
export function RouteFocus() {
  const path = usePathname();
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
