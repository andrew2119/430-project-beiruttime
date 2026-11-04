"use client";

import * as React from "react";

/**
 * For a dialog its parent mounts only while it is shown
 * (`{show && <SomeModal onClose={() => setShow(false)} />}`): keep the Radix
 * dialog open until its exit beat (`pg-modalOut`, styles/motion.css) has
 * played, then hand control back to the parent from `onCloseAutoFocus`, so a
 * close never snaps. Spread `open`/`onOpenChange` on <Dialog>, pass
 * `onCloseAutoFocus` to <DialogContent>, and close from inside the dialog
 * through `requestClose` instead of the parent's `onClose`.
 */
export function useDialogExit(onClose: () => void) {
  const [open, setOpen] = React.useState(true);
  const requestClose = React.useCallback(() => setOpen(false), []);
  const onOpenChange = React.useCallback((next: boolean) => {
    if (!next) setOpen(false);
  }, []);
  const onCloseAutoFocus = React.useCallback(() => onClose(), [onClose]);
  return { open, requestClose, onOpenChange, onCloseAutoFocus };
}
