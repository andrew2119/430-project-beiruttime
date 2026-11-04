'use client';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
/** CP Settings AutoHeight: measurement follows the real content, never a guessed form height. */
export function AutoHeight({ children, className = '' }: { children: ReactNode; className?: string }) {
  const inner=useRef<HTMLDivElement>(null);
  const [height,setHeight]=useState<number|null>(null);
  useLayoutEffect(()=>{
    const element=inner.current;
    if(!element||typeof ResizeObserver==='undefined')return;
    const measure=()=>setHeight(element.offsetHeight);
    measure();
    const observer=new ResizeObserver(measure);observer.observe(element);
    return()=>observer.disconnect();
  },[]);
  return <div className={`proto-set-autoheight ${className}`} style={height===null?undefined:{blockSize:height}}><div ref={inner}>{children}</div></div>;
}
