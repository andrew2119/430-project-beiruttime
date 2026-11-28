'use client';

import { useCallback, useLayoutEffect, useRef, type ReactNode } from 'react';
import { markMotionInput } from '../motion-tokens';
import { cn } from '../utils';
import { nextChoice } from './choice';
import { formatNumber } from './numbers';

export type SegmentedOption = {value:string; label:ReactNode; disabled?:boolean; count?:number|null; 'aria-label'?:string};
function placeThumb(thumb:HTMLElement, x:number, width:number) {
  thumb.style.width = `${width}px`;
  thumb.style.transform = `translateX(${x}px)`;
}

/** One measured decoration; options never own independent active backgrounds. */
export function Segmented({label, value, onValueChange, options, locale = 'en', disabled = false, className}: {label:string; value:string|null; onValueChange:(value:string)=>void; options:readonly SegmentedOption[]; locale?:'en'|'ar'; disabled?:boolean; className?:string}) {
  const root = useRef<HTMLDivElement | null>(null);
  const measure = useCallback(() => {
    const group = root.current;
    if (!group) return;
    const active = group.querySelector<HTMLElement>('[aria-checked="true"]');
    const thumb = group.querySelector<HTMLElement>('.bt-segment-thumb');
    group.toggleAttribute('data-measured', !!active && !!thumb);
    group.toggleAttribute('data-overflow', group.scrollWidth > group.clientWidth + 1);
    if (active && thumb) placeThumb(thumb, active.offsetLeft, active.offsetWidth);
  }, []);
  const attach = useCallback((group:HTMLDivElement | null) => {
    root.current = group;
    if (!group) return;
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(group);
    for (const child of group.querySelectorAll('[role="radio"]')) observer.observe(child);
    return () => observer.disconnect();
  }, [measure]);
  useLayoutEffect(measure, [measure, value, options]);
  const first = options.findIndex(option => !disabled && !option.disabled);
  const active = options.findIndex(option => option.value === value && !disabled && !option.disabled);
  return <div ref={attach} role="radiogroup" aria-label={label} aria-disabled={disabled || undefined} className={cn('bt-segmented', className)}>
    <span className="bt-segment-thumb" aria-hidden="true" />
    {options.map((option,index) => <button type="button" role="radio" key={option.value} aria-checked={option.value === value} aria-label={option['aria-label']} disabled={disabled || option.disabled}
      tabIndex={index === (active < 0 ? first : active) ? 0 : -1} className="bt-segment-item"
      onPointerDown={event => {if (event.currentTarget.parentElement) markMotionInput(event.currentTarget.parentElement, 'pointer');}}
      onClick={() => onValueChange(option.value)}
      onKeyDown={event => {
        const group = event.currentTarget.parentElement;
        if (!group) return;
        markMotionInput(group, 'keyboard');
        if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
        event.preventDefault();
        const next = nextChoice(options.map(item => disabled || !!item.disabled), index, event.key, getComputedStyle(group).direction === 'rtl');
        if (next < 0) return;
        const button = group.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next];
        button?.focus({preventScroll:true});
        button?.scrollIntoView({block:'nearest', inline:'nearest'});
        onValueChange(options[next].value);
      }}>
      <span className="bt-segment-label">{option.label}{option.count == null || !Number.isFinite(option.count) ? null : <> · <bdi className="bt-number">{formatNumber(option.count,locale)}</bdi></>}</span>
    </button>)}
  </div>;
}
