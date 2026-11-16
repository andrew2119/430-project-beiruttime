'use client';

import { useCallback, useId, useState, type ReactNode } from 'react';
import { Button } from './button';
import { cn } from '../utils';
import { scrollRegionKey } from './scroll-keys';
/* eslint jsx-a11y/no-noninteractive-element-interactions: "error" */

/** Overscroll is contained only when the box actually has somewhere to scroll. */
export function ScrollRegion({label,children,className,axis = 'vertical'}: {label:string;children:ReactNode;className?:string;axis?:'vertical'|'horizontal'|'both'}) {
  const attach = useCallback((node:HTMLDivElement | null) => {
    if (!node) return;
    const measure = () => {
      const down = axis !== 'horizontal' && node.scrollHeight > node.clientHeight+1, across = axis !== 'vertical' && node.scrollWidth > node.clientWidth+1;
      node.toggleAttribute('data-overflow',down || across);node.toggleAttribute('data-overflow-y',down);node.toggleAttribute('data-overflow-x',across);
      node.tabIndex = down || across ? 0 : -1;
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    if (node.firstElementChild) observer.observe(node.firstElementChild);
    return () => observer.disconnect();
  }, [axis]);
  // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- This named overflow viewport handles portable scroll keys only when it owns focus; it is not a button.
  return <div ref={attach} role="region" aria-label={label} data-axis={axis} onKeyDown={scrollRegionKey} className={cn('bt-scroll-region', className)}><div className="bt-scroll-content">{children}</div></div>;
}

export function Fold({label, open, onOpenChange, children}: {label:string; open:boolean; onOpenChange:(open:boolean)=>void; children:ReactNode}) {
  const id = useId(), [input, setInput] = useState<'pointer'|'keyboard'|'none'>('none');
  return <section className="bt-fold-group">
    <Button id={`${id}-trigger`} variant="ghost" aria-controls={id} aria-expanded={open} onClick={event => {setInput(event.detail === 0 ? 'keyboard' : 'pointer'); onOpenChange(!open);}}>{label}</Button>
    <div id={id} className="bt-fold" data-state={open ? 'open' : 'closed'} data-bt-motion-input={input} role="region" aria-labelledby={`${id}-trigger`} aria-hidden={open ? undefined : true} inert={open ? undefined : true}>
      <div className="bt-fold-content"><div className="bt-fold-body">{children}</div></div>
    </div>
  </section>;
}
