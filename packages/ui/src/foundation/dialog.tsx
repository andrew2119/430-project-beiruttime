'use client';

import { useId, useRef, type ComponentProps, type ReactNode } from 'react';
import * as Primitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '../utils';
import { markMotionInput } from '../motion-tokens';
import { Button } from './button';
import { ScrollRegion } from './layout';
import { useSurfacePresence } from './presence';
import { keepToastPress, SurfaceProvider, useSurface } from './surface-context';
import { useSurfaceGesture } from './use-surface-gesture';
import { useSurfaceFocus } from './surface-focus';
import { useDirection } from './direction';
import { useSurfaceScroll } from './surface-scroll';

type RootProps = {open:boolean; onOpenChange:(open:boolean)=>void; children:ReactNode};
function DialogRoot({children}: {children:ReactNode}) {const state = useSurface(); return <Primitive.Root open={state.open} onOpenChange={state.change}>{children}</Primitive.Root>;}
export function Dialog({open,onOpenChange,children}:RootProps) {return <SurfaceProvider open={open} onOpenChange={onOpenChange}><DialogRoot>{children}</DialogRoot></SurfaceProvider>;}
export function DialogTrigger({children, label}: {children:ReactNode; label?:string}) {
  const state = useSurface();
  return <Primitive.Trigger type="button" aria-label={label} className="bt-button bt-pressable" data-variant="outline"
    onPointerDown={event=>{state.mark('pointer'); markMotionInput(event.currentTarget,'pointer');}}
    onKeyDown={event=>{state.mark('keyboard'); markMotionInput(event.currentTarget,'keyboard');}}>{children}</Primitive.Trigger>;
}
export function DialogClose({children, label}: {children:ReactNode; label?:string}) {
  const state = useSurface();
  return <Primitive.Close type="button" aria-label={label} className="bt-button bt-pressable" data-variant="outline"
    onPointerDown={event=>{state.mark('pointer'); markMotionInput(event.currentTarget,'pointer');}}
    onKeyDown={event=>{state.mark('keyboard'); markMotionInput(event.currentTarget,'keyboard');}}>{children}</Primitive.Close>;
}
export function DialogTitle({children}: {children:ReactNode}) {return <Primitive.Title className="bt-heading bt-surface-title">{children}</Primitive.Title>;}
export function DialogDescription({children}: {children:ReactNode}) {return <Primitive.Description className="bt-surface-description">{children}</Primitive.Description>;}

type NativeContent = ComponentProps<typeof Primitive.Content>;
export type SurfaceContentProps = {title:string; description?:string; closeLabel:string; children:ReactNode; size?:'read'|'wide'; className?:string; onOpenAutoFocus?:NativeContent['onOpenAutoFocus']; onCloseAutoFocus?:NativeContent['onCloseAutoFocus']; onPointerDownOutside?:NativeContent['onPointerDownOutside']; onInteractOutside?:NativeContent['onInteractOutside']; onEscapeKeyDown?:NativeContent['onEscapeKeyDown']};
export type SheetForm = 'bottom'|'end'|'responsive'|'phone';

/** Both modal forms share presence, focus, outside guards and touch ownership. */
export function SurfaceContent({title,description,closeLabel,children,size = 'read',className,onOpenAutoFocus,onCloseAutoFocus,onPointerDownOutside,onInteractOutside,onEscapeKeyDown,form}: SurfaceContentProps & {form?:SheetForm}) {
  const state = useSurface(), panel = useRef<HTMLDivElement|null>(null), shade = useRef<HTMLDivElement|null>(null);
  const focus = useSurfaceFocus(panel,onOpenAutoFocus,onCloseAutoFocus);
  useSurfaceScroll(state.open);
  const present = useSurfacePresence(state.open,state.input,panel,state.skipExit);
  const descriptionId = useId(), direction = useDirection();
  const attach = useSurfaceGesture(panel,shade,{onPointerDownOutside,onInteractOutside});
  if (!present) return null;
  const motion = form === 'bottom' ? 'bt-sheet-bottom' : form === 'end' ? 'bt-sheet-end' : form === 'responsive' ? 'bt-sheet-responsive' : form === 'phone' ? 'bt-window bt-sheet-phone' : 'bt-window';
  return <Primitive.Portal forceMount><div className="bt-surface-stage" data-form={form} dir={direction.dir} lang={direction.lang}>
    <div ref={shade} aria-hidden="true" inert={state.open ? undefined : true} data-state={state.open ? 'open' : 'closed'} className="bt-shade bt-surface-shade" data-bt-motion-input={state.input}/>
    <Primitive.Content forceMount ref={attach} className={cn('bt-surface-panel',motion,className)} data-form={form} data-size={size} data-dismiss-side={!form || form === 'bottom' || form === 'phone' ? 'down' : undefined}
      data-bt-motion-input={state.input} aria-describedby={description ? descriptionId : undefined} inert={state.open ? undefined : true}
      onPointerDownCapture={()=>state.mark('pointer')} onKeyDownCapture={()=>state.mark('keyboard')}
      onOpenAutoFocus={focus.capture} onCloseAutoFocus={focus.restore} onFocusCapture={focus.reveal}
      onPointerDownOutside={event=>{keepToastPress(event); onPointerDownOutside?.(event);}}
      onInteractOutside={event=>{keepToastPress(event); onInteractOutside?.(event);}}
      onEscapeKeyDown={event=>{state.mark('keyboard'); onEscapeKeyDown?.(event);}}>
      {form && <span className="bt-sheet-handle" data-bt-drag-handle="" aria-hidden="true"/>}
      <header className="bt-surface-header"><div className="bt-surface-heading"><DialogTitle>{title}</DialogTitle>{description && <Primitive.Description id={descriptionId} className="bt-surface-description">{description}</Primitive.Description>}</div>
        <Primitive.Close asChild><Button variant="ghost" size="icon" aria-label={closeLabel}><X aria-hidden="true"/></Button></Primitive.Close>
      </header>
      <ScrollRegion label={title} className="bt-surface-body">{children}</ScrollRegion>
    </Primitive.Content>
  </div></Primitive.Portal>;
}
export function DialogContent({title,description,closeLabel,children,size,className,onOpenAutoFocus,onCloseAutoFocus,onPointerDownOutside,onInteractOutside,onEscapeKeyDown}:SurfaceContentProps) {
  return <SurfaceContent title={title} description={description} closeLabel={closeLabel} size={size} className={className} onOpenAutoFocus={onOpenAutoFocus} onCloseAutoFocus={onCloseAutoFocus} onPointerDownOutside={onPointerDownOutside} onInteractOutside={onInteractOutside} onEscapeKeyDown={onEscapeKeyDown}>{children}</SurfaceContent>;
}
