'use client';

import type { ReactNode } from 'react';
import { Dialog, SurfaceContent, type SheetForm, type SurfaceContentProps } from './dialog';
export { DialogClose as SheetClose, DialogTitle as SheetTitle, DialogDescription as SheetDescription, DialogTrigger as SheetTrigger } from './dialog';
export function Sheet({open,onOpenChange,children}: {open:boolean; onOpenChange:(open:boolean)=>void; children:ReactNode}) {return <Dialog open={open} onOpenChange={onOpenChange}>{children}</Dialog>;}
export function SheetContent({form = 'responsive',title,description,closeLabel,children,size,className,onOpenAutoFocus,onCloseAutoFocus,onPointerDownOutside,onInteractOutside,onEscapeKeyDown}: SurfaceContentProps & {form?:SheetForm}) {
  return <SurfaceContent form={form} title={title} description={description} closeLabel={closeLabel} size={size} className={className} onOpenAutoFocus={onOpenAutoFocus} onCloseAutoFocus={onCloseAutoFocus} onPointerDownOutside={onPointerDownOutside} onInteractOutside={onInteractOutside} onEscapeKeyDown={onEscapeKeyDown}>{children}</SurfaceContent>;
}
