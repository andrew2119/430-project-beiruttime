import { prefersReducedMotion, readMotionToken } from '@beirut-time/ui/motion';
import { readEasingToken } from '@beirut-time/ui/motion-easing';
import { beginThemeIntent } from './theme-intent';
import type { Theme } from './theme';

type Transition = { finished: Promise<void>; skipTransition: () => void };
type ThemeDocument = Document & { startViewTransition?: (update: () => void) => Transition };

/** New controls use this path; existing preference controls retain their pacing.
 * Every control claims the same intent, so late old callbacks cannot win. */
export function changeTheme(next: Theme, apply: (theme: Theme) => void, animate: boolean): void {
  const doc = typeof document === 'undefined' ? undefined : document as ThemeDocument;
  let transition: Transition | undefined;
  const intent = beginThemeIntent(() => {
    try { transition?.skipTransition(); } catch { /* Snapshot support is optional. */ }
    doc?.documentElement.removeAttribute('data-bt-theme-transition');
  });
  let applied = false;
  const update = () => {
    if (!intent.isCurrent() || applied) return;
    applied = true;
    apply(next);
  };
  const duration = readMotionToken('--bt-motion-theme');
  if (!doc || !animate || prefersReducedMotion() || !duration || !readEasingToken('--bt-ease-colour') || typeof doc.startViewTransition !== 'function') {
    doc?.documentElement.removeAttribute('data-bt-theme-transition');
    update();
    intent.release();
    return;
  }
  doc.documentElement.setAttribute('data-bt-theme-transition', '');
  try {
    transition = doc.startViewTransition(update);
    void transition.finished.catch(() => {}).finally(() => {
      if (!intent.isCurrent()) return;
      doc.documentElement.removeAttribute('data-bt-theme-transition');
      intent.release();
    });
  } catch {
    doc.documentElement.removeAttribute('data-bt-theme-transition');
    update();
    intent.release();
  }
}
