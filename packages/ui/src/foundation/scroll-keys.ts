import type { KeyboardEvent } from 'react';
/** Portable region scrolling without taking keys from descendants or the page. */
export function scrollRegionKey(event:KeyboardEvent<HTMLElement>) {
  const box = event.currentTarget;
  if (event.defaultPrevented || event.target !== box || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const axis = box.dataset.axis ?? 'vertical', horizontal = axis === 'horizontal', rtl = getComputedStyle(box).direction === 'rtl';
  const down = Math.max(0,box.scrollHeight-box.clientHeight), across = Math.max(0,box.scrollWidth-box.clientWidth);
  let top = box.scrollTop, left = box.scrollLeft;
  const step = horizontal ? box.clientWidth*0.9 : box.clientHeight*0.9;
  if (['ArrowDown','ArrowUp'].includes(event.key) && !horizontal) top += event.key === 'ArrowDown' ? 80 : -80;
  else if (['ArrowRight','ArrowLeft'].includes(event.key) && axis !== 'vertical') left += event.key === 'ArrowRight' ? 80 : -80;
  else if (['PageDown','PageUp'].includes(event.key)) {const delta = event.key === 'PageDown' ? step : -step;if (horizontal) left += rtl ? -delta : delta;else top += delta;}
  else if (event.key === 'Home' || event.key === 'End') {if (horizontal) left = event.key === 'Home' ? 0 : rtl ? -across : across;else top = event.key === 'Home' ? 0 : down;}
  else return;
  top = Math.max(0,Math.min(down,top));left = Math.max(rtl ? -across : 0,Math.min(rtl ? 0 : across,left));
  if (Math.abs(top-box.scrollTop) <= 1 && Math.abs(left-box.scrollLeft) <= 1) return;
  event.preventDefault();box.scrollTo({top,left,behavior:'instant'});
}
