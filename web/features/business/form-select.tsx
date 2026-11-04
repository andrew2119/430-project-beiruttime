"use client";

import { Children, isValidElement, useEffect, useRef, useState, type ComponentProps, type ReactElement } from "react";
import { Select } from "@beirut-time/ui";

type NativeProps = ComponentProps<"select">;
/** CP's lazy single-choice menu with a native form bridge. The real select keeps
 * FormData, reset, existing draft restoration, and change handlers intact. */
export function FormSelect({ children, value, defaultValue, id, className, ...props }: NativeProps) {
  const options = Children.toArray(children).filter(isValidElement).map(child => {
    const option = child as ReactElement<ComponentProps<"option">>;
    return { value: String(option.props.value ?? ""), label: option.props.children, disabled: option.props.disabled };
  });
  const [local, setLocal] = useState(String(defaultValue ?? options[0]?.value ?? ""));
  const native = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    const node = native.current;
    if (!node) return;
    const sync = () => setLocal(node.value);
    const reset = () => queueMicrotask(sync);
    node.addEventListener("change", sync);
    node.form?.addEventListener("reset", reset);
    return () => { node.removeEventListener("change", sync); node.form?.removeEventListener("reset", reset); };
  }, []);
  return <span className="business-select-control" dir={props.dir}>
    <Select id={id} className={className} value={String(value ?? local)} disabled={props.disabled} options={options}
      aria-label={props["aria-label"]} aria-labelledby={props["aria-labelledby"]}
      onValueChange={next => {
        const node = native.current;
        if (!node) return;
        node.value = next;
        setLocal(next);
        node.dispatchEvent(new Event("change", { bubbles: true }));
      }} />
    <select {...props} ref={native} value={value} defaultValue={defaultValue} hidden aria-hidden="true" tabIndex={-1}>{children}</select>
  </span>;
}
