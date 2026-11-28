"use client";

import { Children, isValidElement, useEffect, useRef, useState, type ComponentProps, type ReactElement } from "react";
import { Select } from "@beirut-time/ui/foundation";

import { useLocale } from "@/shell/locale-context";
import en from "./en.json";
import ar from "./ar.json";
type NativeProps = ComponentProps<"select"> & { label?: string };
/** The shared lazy single-choice menu with a native form bridge. The real select keeps
 * FormData, reset, existing draft restoration, and change handlers intact. */
export function CanonicalSelect({ children, value, defaultValue, id, label, ...props }: NativeProps) {
  const t = useLocale() === "ar" ? ar : en;
  const options = Children.toArray(children).filter(isValidElement).map(child => {
    const option = child as ReactElement<ComponentProps<"option">>;
    return { value: String(option.props.value ?? ""), label: String(option.props.children ?? ""), disabled: option.props.disabled };
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
    <Select label={label ?? props["aria-label"] ?? ""} messages={{placeholder:t.choose,filter:t.scope,emptyTitle:t.empty,emptyBody:t.empty,close:t.close,loading:t.loading,errorTitle:t.retry,errorBody:t.unavailable,retry:t.retry}} id={id} value={String(value ?? local)} disabled={props.disabled} options={options}
      onValueChange={next => {
        const node = native.current;
        if (!node) return;
        node.value = next;
        setLocal(next);
        node.dispatchEvent(new Event("change", { bubbles: true }));
      }} />
    <select name={props.name} disabled={props.disabled} required={props.required} onChange={props.onChange} form={props.form} dir={props.dir} ref={native} value={value} defaultValue={defaultValue ?? options[0]?.value} hidden aria-hidden="true" tabIndex={-1}>{children}</select>
  </span>;
}
