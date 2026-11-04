"use client";

import { useRef, type ComponentProps } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { cn } from "./utils";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;
export const SheetTitle = Dialog.Title;

/** Modal sheet uses the same focus and dismissal engine as DialogContent.
 * The caller supplies edge geometry and a title; the scrim needs no blur.
 */
export function SheetContent({ className, children, onOpenAutoFocus, onCloseAutoFocus, ...props }: ComponentProps<typeof Dialog.Content>) {
  const returnFocus = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
      <Dialog.Content
        className={cn("fixed z-50", className)}
        onOpenAutoFocus={(event) => {
          returnFocus.current = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
            ? document.activeElement : null;
          onOpenAutoFocus?.(event);
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event);
          if (!event.defaultPrevented && returnFocus.current?.isConnected) {
            event.preventDefault();
            returnFocus.current.focus({ preventScroll: true });
          }
        }}
        {...props}
      >
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}
