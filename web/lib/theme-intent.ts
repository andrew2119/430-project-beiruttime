let revision = 0;
let cancellation: (() => void) | undefined;

/** Shared request ownership, not another preference store. Existing and new
 * controls supersede one another without loading snapshot/curve code globally. */
export function beginThemeIntent(onCancel?: () => void) {
  const previous = cancellation;
  const current = ++revision;
  cancellation = onCancel;
  try { previous?.(); } catch { /* A discarded snapshot cannot block new input. */ }
  return {
    isCurrent: () => current === revision,
    release: () => { if (current === revision) cancellation = undefined; },
  };
}
