'use client';

import { createContext, useCallback, useContext, useMemo, useRef, useState, useId, type ReactNode } from 'react';
export type SurfaceInput = 'pointer'|'keyboard'|'none';
type Surface = {open:boolean; contentId:string; triggerId:string; input:SurfaceInput; skipExit:boolean; mark:(input:SurfaceInput)=>void; change:(open:boolean)=>void; dismissInstant:()=>void};
const Context = createContext<Surface|null>(null);
export function SurfaceProvider({open, onOpenChange, children, initialInput = 'none'}: {open:boolean; onOpenChange:(open:boolean)=>void; children:ReactNode; initialInput?:SurfaceInput}) {
  const id = useId();
  const [input,setInput] = useState<SurfaceInput>(initialInput);
  const [skipExit,setSkipExit] = useState(false);
  const mode = useRef<SurfaceInput>(initialInput);
  const mark = useCallback((next:SurfaceInput) => {mode.current = next; setInput(next); setSkipExit(false);}, []);
  const change = useCallback((next:boolean) => {setSkipExit(false); setInput(mode.current); onOpenChange(next);}, [onOpenChange]);
  const dismissInstant = useCallback(() => {setSkipExit(true); onOpenChange(false);}, [onOpenChange]);
  const value = useMemo(()=>({open,contentId:`${id}-content`,triggerId:`${id}-trigger`,input,skipExit,mark,change,dismissInstant}),[open,id,input,skipExit,mark,change,dismissInstant]);
  return <Context value={value}>{children}</Context>;
}
export function useSurface():Surface {const value = useContext(Context); if (!value) throw new Error('Surface parts must be inside their shared root.'); return value;}

export function inToastRegion(target:EventTarget|null):target is Element {return typeof Element !== 'undefined' && target instanceof Element && !!target.closest('[data-bt-toast-region],[data-sonner-toaster]');}
export function keepToastPress(event:{target:EventTarget|null; preventDefault:()=>void}) {if (inToastRegion(event.target)) event.preventDefault();}
