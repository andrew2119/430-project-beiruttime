'use client';

import type { ComponentProps, ReactNode } from 'react';
import * as Primitive from '@radix-ui/react-dropdown-menu';
import { Check } from 'lucide-react';
import { cn } from '../utils';
import { markMotionInput } from '../motion-tokens';
import { keepToastPress, SurfaceProvider, useSurface } from './surface-context';
import { useDirection } from './direction';
import { usePopupFrame } from './use-popup-frame';

function Root({children}: {children:ReactNode}) {const state = useSurface(), direction = useDirection(); return <Primitive.Root modal={false} dir={direction.dir} open={state.open} onOpenChange={state.change}>{children}</Primitive.Root>;}
export function DropdownMenu({open,onOpenChange,children}: {open:boolean; onOpenChange:(open:boolean)=>void; children:ReactNode}) {return <SurfaceProvider open={open} onOpenChange={onOpenChange}><Root>{children}</Root></SurfaceProvider>;}
export function DropdownMenuTrigger({children,label,disabled}: {children:ReactNode; label?:string; disabled?:boolean}) {
  const state = useSurface();
  return <Primitive.Trigger type="button" disabled={disabled} aria-label={label} className="bt-button bt-pressable" data-variant="outline"
    onPointerDown={event=>{state.mark('pointer');markMotionInput(event.currentTarget,'pointer');}}
    onKeyDown={event=>{state.mark('keyboard');markMotionInput(event.currentTarget,'keyboard');}}>{children}</Primitive.Trigger>;
}
type Native = ComponentProps<typeof Primitive.Content>;
export function DropdownMenuContent({label,children,className,align = 'end',onCloseAutoFocus,onPointerDownOutside,onInteractOutside}: {label:string; children:ReactNode; className?:string; align?:'start'|'center'|'end'; onCloseAutoFocus?:Native['onCloseAutoFocus']; onPointerDownOutside?:Native['onPointerDownOutside']; onInteractOutside?:Native['onInteractOutside']}) {
  const {state,present,attach,gap,focus} = usePopupFrame({onPointerDownOutside,onInteractOutside},undefined,onCloseAutoFocus), direction = useDirection();
  if (!present) return null;
  return <Primitive.Portal forceMount><Primitive.Content forceMount ref={attach} aria-label={label} align={align} sideOffset={gap} collisionPadding={gap} lang={direction.lang}
    className={cn('bt-popup bt-menu',className)} data-bt-motion-input={state.input} inert={state.open ? undefined : true}
    onCloseAutoFocus={focus.restore} onFocusCapture={focus.reveal} onEscapeKeyDown={()=>state.mark('keyboard')}
    onPointerDownCapture={()=>state.mark('pointer')} onKeyDownCapture={()=>state.mark('keyboard')}
    onPointerDownOutside={event=>{keepToastPress(event);onPointerDownOutside?.(event);}} onInteractOutside={event=>{keepToastPress(event);onInteractOutside?.(event);}}>{children}</Primitive.Content></Primitive.Portal>;
}
export function DropdownMenuItem({children,disabled = false,destructive = false,onSelect}: {children:ReactNode; disabled?:boolean; destructive?:boolean; onSelect?:(event:Event)=>void}) {return <Primitive.Item disabled={disabled} onSelect={onSelect} className="bt-menu-item" data-destructive={destructive ? '' : undefined}>{children}</Primitive.Item>;}
export function DropdownMenuRadioGroup({value,onValueChange,children}: {value:string; onValueChange:(value:string)=>void; children:ReactNode}) {return <Primitive.RadioGroup value={value} onValueChange={onValueChange}>{children}</Primitive.RadioGroup>;}
export function DropdownMenuRadioItem({value,disabled = false,children}: {value:string; disabled?:boolean; children:ReactNode}) {return <Primitive.RadioItem value={value} disabled={disabled} className="bt-menu-item bt-menu-radio"><span className="bt-menu-check" aria-hidden="true"><Primitive.ItemIndicator><Check/></Primitive.ItemIndicator></span><span className="bt-menu-label-copy">{children}</span></Primitive.RadioItem>;}
export function DropdownMenuLabel({children}: {children:ReactNode}) {return <Primitive.Label className="bt-menu-label">{children}</Primitive.Label>;}
export function DropdownMenuSeparator() {return <Primitive.Separator className="bt-menu-separator"/>;}
