function padding(node:HTMLElement, value:number) {node.style.paddingBlockEnd = `${Math.max(0,value)}px`;}
function scrollFrame(node:HTMLElement):HTMLElement|null {
  for (let candidate:HTMLElement|null = node; candidate; candidate = candidate.parentElement) if (/auto|scroll/.test(getComputedStyle(candidate).overflowY) && candidate.scrollHeight > candidate.clientHeight + 1) return candidate;
  return document.scrollingElement instanceof HTMLElement ? document.scrollingElement : null;
}
/** Discrete stack/resize geometry only; transforms never drive this reserve. */
export function reserveToastSpace(region:HTMLElement, content:()=>HTMLElement|null) {
  let owned:HTMLElement|null = null, original = '';
  const restore = () => {if (owned) owned.style.paddingBlockEnd = original;};
  const measure = () => {
    const frame = content();if (!frame) return;
    if (frame !== owned) {restore();owned = frame;original = frame.style.paddingBlockEnd;}
    const scroll = scrollFrame(frame), atFoot = !!scroll && scroll.scrollTop >= scroll.scrollHeight-scroll.clientHeight-1;
    restore();
    const base = Number.parseFloat(getComputedStyle(frame).paddingBlockEnd) || 0;
    const bottom = Number.parseFloat(getComputedStyle(region).bottom) || 0;
    padding(frame,base+(region.hasAttribute('data-active') ? region.clientHeight+bottom : 0));
    if (atFoot && scroll) scroll.scrollTop = scroll.scrollHeight;
  };
  return {measure,restore};
}
