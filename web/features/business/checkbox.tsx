'use client';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Checkbox as SharedCheckbox } from '@beirut-time/ui/foundation';
/** Native-form compatibility; drawing and interaction stay in the shared control. */
export function Checkbox({children,defaultChecked=false,name,value}: {children:ReactNode;defaultChecked?:boolean;name:string;value?:string;className?:string}) {
  const [checked,setChecked] = useState(defaultChecked);
  const wrapper = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = wrapper.current?.querySelector('input');
    if (!node) return;
    node.defaultChecked = defaultChecked;
    const sync = () => setChecked(node.checked);
    const reset = () => queueMicrotask(sync);
    node.addEventListener('change',sync);
    node.form?.addEventListener('reset',reset);
    return () => {node.removeEventListener('change',sync);node.form?.removeEventListener('reset',reset);};
  },[defaultChecked]);
  return <span ref={wrapper}><SharedCheckbox label={String(children)} checked={checked} onCheckedChange={setChecked} name={name} value={value} /></span>;
}
