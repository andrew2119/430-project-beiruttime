import type * as React from "react";

/**
 * The pressed look of a phone listing row appears as soon as it is touched.
 *
 * A finger landing on the row marks it `data-pressed` inside the touch's own event, so
 * the first frame drawn after the touch already shows the look; each list's stylesheet
 * draws it. The browser taking the finger for a scroll cancels the pointer, which
 * clears the mark. The tap's click arrives just after the finger lifts and turns the
 * mark into `data-pressed="open"`, which stays until the page changes and the row goes
 * with it, so the row reads as pressed while the destination page draws. A lift that brings no
 * click (a long press) clears the mark after LIFT_MS. A mouse never marks a row, so
 * desktop hover and click stay as they were.
 *
 * Spread `pressLook` on a row that is its own opener, and `coverPressLook` on the
 * stretched cover that opens a row (the cover's parent takes the mark).
 */

type Row = (event: React.SyntheticEvent<HTMLElement>) => HTMLElement;
type PressLook = {
  onPointerDown: React.PointerEventHandler<HTMLElement>;
  onPointerUp: React.PointerEventHandler<HTMLElement>;
  onPointerCancel: React.PointerEventHandler<HTMLElement>;
  onClickCapture: React.MouseEventHandler<HTMLElement>;
};

const MARK = "data-pressed";
/** Longer than any tap's lift-to-click gap, short enough that a long press lets go. */
const LIFT_MS = 300;

let lifted: HTMLElement | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;

/** Ends the last lift that brought no click; a row its click opened keeps its mark. */
function settle() {
  clearTimeout(timer);
  if (lifted?.getAttribute(MARK) === "") lifted.removeAttribute(MARK);
  lifted = null;
}

function handlers(row: Row): PressLook {
  return {
    onPointerDown(event) {
      if (event.pointerType !== "touch") return;
      settle();
      row(event).setAttribute(MARK, "");
    },
    // A mouse's lift finds no mark, so it needs no check of its own.
    onPointerUp(event) {
      settle();
      lifted = row(event);
      timer = setTimeout(settle, LIFT_MS);
    },
    onPointerCancel(event) {
      row(event).removeAttribute(MARK);
    },
    onClickCapture(event) {
      if (row(event).hasAttribute(MARK)) row(event).setAttribute(MARK, "open");
    },
  };
}

export const pressLook = handlers((event) => event.currentTarget);
export const coverPressLook = handlers((event) => event.currentTarget.parentElement!);
