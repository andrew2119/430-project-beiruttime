"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "./utils";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;

function DialogContent({
  className,
  children,
  onOpenAutoFocus,
  onCloseAutoFocus,
  onFocusCapture,
  closeLabel,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { closeLabel: string }) {
  const returnFocus = React.useRef<HTMLElement | null>(null);
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="pg-overlay fixed inset-0 z-50 bg-black/40" />
      <DialogPrimitive.Content
        onOpenAutoFocus={(event) => {
          returnFocus.current = document.activeElement instanceof HTMLElement
            ? document.activeElement : null;
          onOpenAutoFocus?.(event);
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event);
          // Controlled, lazy dialogs can have no Radix Trigger in their tree.
          // Restore their invoking control as well as ordinary Trigger dialogs.
          if (!event.defaultPrevented && returnFocus.current?.isConnected) {
            event.preventDefault();
            returnFocus.current.focus({ preventScroll: true });
          }
        }}
        onFocusCapture={(event) => {
          onFocusCapture?.(event);
          // Keyboard focus reveals the whole control inside a scrolling dialog.
          // Firefox scrolls a focused element into view only when no part of it
          // is visible, so a control that is a sliver at the dialog's edge stayed
          // hidden there; "nearest" is a no-op when the control is already whole.
          if (!event.defaultPrevented && event.target instanceof HTMLElement) {
            event.target.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
          }
        }}
        className={cn(
          "pg-modal ui-dialog",
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close aria-label={closeLabel} className="pg-iconbtn ui-dialog-close rounded-md p-1 text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
          <X className="size-4" aria-hidden />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn("ui-dialog-title", className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      className={cn("ui-dialog-description", className)}
      {...props}
    />
  );
}

export { Dialog, DialogTrigger, DialogClose, DialogContent, DialogTitle, DialogDescription };
