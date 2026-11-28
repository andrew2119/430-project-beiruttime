'use client';

import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { Button, Dialog, DialogTrigger, DialogContent, DialogClose, DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuLabel, DropdownMenuSeparator, Input, Popover, PopoverTrigger, PopoverContent, Sheet, SheetTrigger, SheetContent, SheetClose, State, formatNumber, toast } from '@beirut-time/ui/foundation';
import { readMotionToken } from '@beirut-time/ui/motion';
import type { ReviewDataMode } from '../../tests/fixtures/worst-case';
import { ComponentCase } from './case';
import { boardBoundary } from './boundary';
import type { BoardCopy } from './copy';
import type { BoardLocale } from './model';
export type BoardSurface = 'dialog'|'wide'|'bottom'|'end'|'responsive'|'phone'|'popover'|'menu';
export function PopupExample({copy,initialOpen = false}: {copy:BoardCopy;initialOpen?:boolean}) {
  const [open,setOpen] = useState(initialOpen);
  return <Popover open={open} onOpenChange={setOpen}><PopoverTrigger>{copy.popupLabel}</PopoverTrigger><PopoverContent label={copy.popupLabel} closeLabel={copy.close}><p className="bt-text">{copy.surfaceBody}</p><Input label={copy.displayName} placeholder={copy.placeholder}/><Button variant="outline" onClick={()=>toast.info(copy.toastInfo,{description:copy.toastBody})}>{copy.toastInfo}</Button></PopoverContent></Popover>;
}
export function MenuExample({copy,initialOpen = false}: {copy:BoardCopy;initialOpen?:boolean}) {
  const [open,setOpen] = useState(initialOpen), [choice,setChoice] = useState('collect');
  return <DropdownMenu open={open} onOpenChange={setOpen}><DropdownMenuTrigger>{copy.menuLabel}</DropdownMenuTrigger><DropdownMenuContent label={copy.menuLabel}>
    <DropdownMenuLabel>{copy.menuLabel}</DropdownMenuLabel><DropdownMenuItem onSelect={()=>toast.info(copy.toastInfo)}>{copy.menuInspect}</DropdownMenuItem><DropdownMenuItem disabled>{copy.disabled}</DropdownMenuItem><DropdownMenuSeparator/>
    <DropdownMenuRadioGroup value={choice} onValueChange={setChoice}><DropdownMenuRadioItem value="collect">{copy.radioOne}</DropdownMenuRadioItem><DropdownMenuRadioItem value="deliver">{copy.radioTwo}</DropdownMenuRadioItem><DropdownMenuRadioItem value="disabled" disabled>{copy.disabled}</DropdownMenuRadioItem></DropdownMenuRadioGroup><DropdownMenuSeparator/>
    <DropdownMenuItem destructive onSelect={()=>toast.warning(copy.toastWarning)}>{copy.menuDanger}</DropdownMenuItem>
  </DropdownMenuContent></DropdownMenu>;
}
function SurfaceBody({copy,description,reopen}: {copy:BoardCopy;description:string;reopen?:(event:MouseEvent<HTMLButtonElement>)=>void}) {
  const [nested,setNested] = useState(false);
  return <div className="bt-board-stack"><p className="bt-text">{copy.surfaceBody}</p><Input label={copy.displayName} placeholder={copy.placeholder}/><div className="bt-board-row"><PopupExample copy={copy}/><MenuExample copy={copy}/><Button variant="outline" onClick={()=>toast.info(copy.toastInfo,{description:copy.toastBody,action:{label:copy.toastAction,run:()=>{toast.success(copy.toastSuccess);return false;}}})}>{copy.toastInfo}</Button></div>
    {reopen && <Button variant="outline" onClick={reopen}>{copy.reopen}</Button>}
    <Dialog open={nested} onOpenChange={setNested}><DialogTrigger>{copy.nested}</DialogTrigger><DialogContent title={copy.nestedTitle} description={copy.surfaceBody} closeLabel={copy.close}><div className="bt-board-stack"><Input label={copy.notes}/><PopupExample copy={copy}/><MenuExample copy={copy}/><Button onClick={()=>toast.success(copy.toastSuccess,{description:copy.toastBody})}>{copy.toastSuccess}</Button><DialogClose>{copy.close}</DialogClose></div></DialogContent></Dialog>
    {description ? <p className="bt-text">{description}</p> : <State headingLevel={3} title={copy.emptyTitle} body={copy.emptyBody}/>}<Input label={copy.notes} placeholder={copy.placeholder}/>
  </div>;
}
export function SurfaceCases({mode,copy,locale,initialSurface = null}: {mode:ReviewDataMode;copy:BoardCopy;locale:BoardLocale;initialSurface?:BoardSurface|null}) {
  const [surface,setSurface] = useState<BoardSurface|null>(initialSurface), timers = useRef(new Set<ReturnType<typeof setTimeout>>()), intent = useRef(0), sample = boardBoundary(mode,locale);
  useEffect(()=>{const pending = timers.current;return ()=>{for (const timer of pending) clearTimeout(timer);};},[]);
  const change = (kind:BoardSurface) => (open:boolean)=>{intent.current++;setSurface(current=>open ? kind : current === kind ? null : current);};
  const reopen = (kind:BoardSurface)=>(event:MouseEvent<HTMLButtonElement>)=>{
    const duration = event.detail > 0 ? readMotionToken('--bt-motion-exit',event.currentTarget) ?? 0 : 0;
    const version = ++intent.current;setSurface(null);const timer = setTimeout(()=>{timers.current.delete(timer);if (version === intent.current) setSurface(kind);},duration/2);timers.current.add(timer);
  };
  return <>
    <ComponentCase id="dialog" title={copy.headings.dialog}>{(['dialog','wide'] as const).map(kind=><Dialog key={kind} open={surface === kind} onOpenChange={change(kind)}><DialogTrigger>{kind === 'wide' ? copy.wideWindow : copy.open}</DialogTrigger><DialogContent size={kind === 'wide' ? 'wide' : 'read'} title={sample.title} description={copy.surfaceBody} closeLabel={copy.close}><SurfaceBody copy={copy} description={sample.description} reopen={reopen(kind)}/><DialogClose>{copy.close}</DialogClose></DialogContent></Dialog>)}</ComponentCase>
    {(['bottom','end','responsive','phone'] as const).map(form=><ComponentCase key={form} id={`sheet-${form}`} title={copy.headings[`sheet-${form}`]}><Sheet open={surface === form} onOpenChange={change(form)}><SheetTrigger>{copy.open}</SheetTrigger><SheetContent form={form} title={sample.title} description={copy.surfaceBody} closeLabel={copy.close}><SurfaceBody copy={copy} description={sample.description} reopen={reopen(form)}/><SheetClose>{copy.close}</SheetClose></SheetContent></Sheet></ComponentCase>)}
    <ComponentCase id="popover" title={copy.headings.popover}><PopupExample copy={copy} initialOpen={surface === 'popover'}/></ComponentCase>
    <ComponentCase id="menu" title={copy.headings.menu}><MenuExample copy={copy} initialOpen={surface === 'menu'}/></ComponentCase>
    <ToastCase copy={copy} locale={locale} initialCount={sample.count}/>
  </>;
}
export function ToastCase({copy,locale,initialCount = 0}: {copy:BoardCopy;locale:BoardLocale;initialCount?:number}) {
  const [count,setCount] = useState(initialCount), [loading,setLoading] = useState<string|null>(null);
  const options = {description:copy.toastBody,action:{label:copy.toastAction,run:()=>{setCount(value=>value+1);return false;}}};
  return <ComponentCase id="toast" title={copy.headings.toast}><div className="bt-board-row"><Button variant="outline" onClick={()=>toast.info(copy.toastInfo,options)}>{copy.toastInfo}</Button><Button variant="outline" onClick={()=>toast.success(copy.toastSuccess,options)}>{copy.toastSuccess}</Button><Button variant="outline" onClick={()=>toast.warning(copy.toastWarning,options)}>{copy.toastWarning}</Button><Button variant="outline" onClick={()=>toast.error(copy.toastError,options)}>{copy.toastError}</Button><Button variant="outline" onClick={()=>setLoading(toast.loading(copy.toastLoading,{description:copy.toastBody}))}>{copy.toastLoading}</Button><Button variant="outline" disabled={!loading} onClick={()=>{if (loading) toast.success(copy.toastSuccess,{id:loading});setLoading(null);}}>{copy.finishLoading}</Button><Button variant="outline" onClick={()=>toast.error(copy.toastError,{description:copy.toastBody})}>{copy.repeatNotice}</Button><Button variant="ghost" onClick={()=>{toast.dismiss();setLoading(null);}}>{copy.clearToasts}</Button></div><p className="bt-text" role="status">{copy.toastCounter}: <bdi>{formatNumber(count,locale)}</bdi></p></ComponentCase>;
}
