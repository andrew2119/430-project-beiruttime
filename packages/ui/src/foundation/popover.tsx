'use client';

import type { ComponentProps, KeyboardEventHandler, ReactNode, Ref } from 'react';
import * as Primitive from '@radix-ui/react-popover';
import { X } from 'lucide-react';
import { cn } from '../utils';
import { markMotionInput } from '../motion-tokens';
import { Button } from './button';
import { ScrollRegion } from './layout';
import { useDirection } from './direction';
import { keepToastPress, SurfaceProvider, useSurface, type SurfaceInput } from './surface-context';
import { usePopupFrame } from './use-popup-frame';

function Root({children}: {children:ReactNode}) {const state = useSurface(); return <Primitive.Root open={state.open} onOpenChange={state.change}>{children}</Primitive.Root>;}
export function Popover({open,onOpenChange,children,initialInput}: {open:boolean; onOpenChange:(open:boolean)=>void; children:ReactNode; initialInput?:SurfaceInput}) {return <SurfaceProvider open={open} onOpenChange={onOpenChange} initialInput={initialInput}><Root>{children}</Root></SurfaceProvider>;}
export function PopoverTrigger({children,label,disabled,ref,id,className,role,required,invalid,describedBy,controls,onKeyDown}: {children:ReactNode; label?:string; disabled?:boolean; ref?:Ref<HTMLButtonElement>; id?:string; className?:string; role?:'combobox'; required?:boolean; invalid?:boolean; describedBy?:string; controls?:string; onKeyDown?:KeyboardEventHandler<HTMLButtonElement>}) {
  const state = useSurface();
  return <Primitive.Trigger ref={ref} id={id ?? state.triggerId} type="button" disabled={disabled} aria-label={label} role={role} aria-required={required} aria-invalid={invalid} aria-describedby={describedBy} aria-controls={controls ?? state.contentId} className={cn('bt-button bt-pressable',className)} data-variant="outline"
    onPointerDown={event=>{state.mark('pointer');markMotionInput(event.currentTarget,'pointer');}}
    onKeyDown={event=>{state.mark('keyboard');markMotionInput(event.currentTarget,'keyboard');onKeyDown?.(event);}}>{children}</Primitive.Trigger>;
}
type Native = ComponentProps<typeof Primitive.Content>;
export function PopoverContent({id,label,closeLabel,children,className,align = 'end',onOpenAutoFocus,onCloseAutoFocus,onPointerDownOutside,onInteractOutside}: {id?:string; label:string; closeLabel:string; children:ReactNode; className?:string; align?:'start'|'center'|'end'; onOpenAutoFocus?:Native['onOpenAutoFocus']; onCloseAutoFocus?:Native['onCloseAutoFocus']; onPointerDownOutside?:Native['onPointerDownOutside']; onInteractOutside?:Native['onInteractOutside']}) {
  const {state,present,attach,gap,focus} = usePopupFrame({onPointerDownOutside,onInteractOutside},onOpenAutoFocus,onCloseAutoFocus), direction = useDirection();
  if (!present) return null;
  return <Primitive.Portal forceMount><Primitive.Content forceMount ref={attach} id={id ?? state.contentId} align={align} sideOffset={gap} collisionPadding={gap} dir={direction.dir} lang={direction.lang}
    aria-label={label} aria-labelledby={undefined} className={cn('bt-popup bt-popover',className)} data-bt-motion-input={state.input} inert={state.open ? undefined : true}
    onOpenAutoFocus={focus.capture} onCloseAutoFocus={focus.restore} onFocusCapture={focus.reveal}
    onPointerDownCapture={()=>state.mark('pointer')} onKeyDownCapture={()=>state.mark('keyboard')}
    onEscapeKeyDown={()=>state.mark('keyboard')}
    onPointerDownOutside={event=>{keepToastPress(event);onPointerDownOutside?.(event);}} onInteractOutside={event=>{keepToastPress(event);onInteractOutside?.(event);}}>
    <header className="bt-popup-header"><h2 className="bt-popup-title">{label}</h2><Button variant="ghost" size="icon" aria-label={closeLabel} onClick={()=>state.change(false)}><X aria-hidden="true"/></Button></header>
    <ScrollRegion label={label} className="bt-popup-body">{children}</ScrollRegion>
  </Primitive.Content></Primitive.Portal>;
}
