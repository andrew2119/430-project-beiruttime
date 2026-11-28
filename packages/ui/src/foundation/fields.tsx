'use client';

import { useId, type KeyboardEventHandler, type ReactNode, type Ref } from 'react';
import { cn } from '../utils';

export type FieldProps = {id?:string; label:string; hint?:string; error?:string; disabled?:boolean; required?:boolean; className?:string};
export function Field({id, label, hint, error, className, children, inline = false}: FieldProps & {id:string; children:ReactNode; inline?:boolean}) {
  return <div className={cn('bt-field', className)} data-inline={inline ? '' : undefined}>
    <label htmlFor={id} className="bt-field-label">{label}</label>{children}
    {hint && <p id={`${id}-hint`} className="bt-field-hint">{hint}</p>}
    {error && <p id={`${id}-error`} className="bt-field-error" role="alert">{error}</p>}
  </div>;
}
export function description(id:string, hint?:string, error?:string) {return [hint ? `${id}-hint` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ') || undefined;}

export type InputProps = FieldProps & {
  value?:string; defaultValue?:string; onValueChange?:(value:string)=>void; name?:string;
  type?:'text'|'email'|'tel'|'password'|'search'|'url'|'number'|'date'; inputMode?:'text'|'email'|'tel'|'url'|'numeric'|'decimal'|'search';
  placeholder?:string; autoComplete?:string; readOnly?:boolean; min?:string|number; max?:string|number; step?:string|number; ref?:Ref<HTMLInputElement>; onKeyDown?:KeyboardEventHandler<HTMLInputElement>;
};
export function Input({id: supplied, label, hint, error, disabled, required, className, value, defaultValue, onValueChange, name, type = 'text', inputMode, placeholder, autoComplete, readOnly, min, max, step, ref, onKeyDown}: InputProps) {
  const generated = useId(), id = supplied ?? generated;
  return <Field id={id} label={label} hint={hint} error={error} className={className}>
    <input ref={ref} id={id} name={name} type={type} value={value} defaultValue={defaultValue} onChange={event => onValueChange?.(event.currentTarget.value)}
      inputMode={inputMode} placeholder={placeholder} autoComplete={autoComplete} autoCapitalize={type === 'email' || type === 'url' ? 'none' : undefined}
      disabled={disabled} required={required} readOnly={readOnly} min={min} max={max} step={step} onKeyDown={onKeyDown}
      aria-invalid={error ? true : undefined} aria-describedby={description(id, hint, error)} className="bt-input" />
  </Field>;
}

export function Textarea({id: supplied, label, hint, error, disabled, required, className, value, defaultValue, onValueChange, name, placeholder, readOnly, rows = 3}: FieldProps & {value?:string; defaultValue?:string; onValueChange?:(value:string)=>void; name?:string; placeholder?:string; readOnly?:boolean; rows?:number}) {
  const generated = useId(), id = supplied ?? generated;
  return <Field id={id} label={label} hint={hint} error={error} className={className}>
    <textarea id={id} name={name} value={value} defaultValue={defaultValue} onChange={event => onValueChange?.(event.currentTarget.value)} placeholder={placeholder}
      disabled={disabled} required={required} readOnly={readOnly} rows={rows} aria-invalid={error ? true : undefined} aria-describedby={description(id, hint, error)} className="bt-input bt-textarea" />
  </Field>;
}

export function Label({htmlFor, children}: {htmlFor:string; children:ReactNode}) {return <label htmlFor={htmlFor} className="bt-field-label">{children}</label>;}

type CheckProps = FieldProps & {checked:boolean; onCheckedChange?:(checked:boolean)=>void; name?:string; value?:string};
function CheckField({id: supplied, label, hint, error, disabled, required, className, checked, onCheckedChange, name, value, type = 'checkbox', switchRole = false}: CheckProps & {type?:'checkbox'|'radio'; switchRole?:boolean}) {
  const generated = useId(), id = supplied ?? generated;
  return <Field id={id} label={label} hint={hint} error={error} className={className} inline>
    <span className="bt-check-control" data-kind={switchRole ? 'switch' : type}>
      <input id={id} name={name} value={value} type={type} role={switchRole ? 'switch' : undefined} checked={checked} onChange={event => onCheckedChange?.(event.currentTarget.checked)}
        disabled={disabled} required={required} aria-invalid={error ? true : undefined} aria-describedby={description(id, hint, error)} className="bt-check" />
      <span className="bt-check-drawing" aria-hidden="true" />
    </span>
  </Field>;
}
export function Checkbox({id, label, hint, error, disabled, required, className, checked, onCheckedChange, name, value}: CheckProps) {return <CheckField id={id} label={label} hint={hint} error={error} disabled={disabled} required={required} className={className} checked={checked} onCheckedChange={onCheckedChange} name={name} value={value}/>;}
export function Radio({id, label, hint, error, disabled, required, className, checked, onCheckedChange, name, value}: CheckProps) {return <CheckField type="radio" id={id} label={label} hint={hint} error={error} disabled={disabled} required={required} className={className} checked={checked} onCheckedChange={onCheckedChange} name={name} value={value}/>;}
export function Switch({id, label, hint, error, disabled, required, className, checked, onCheckedChange, name, value}: CheckProps) {return <CheckField switchRole id={id} label={label} hint={hint} error={error} disabled={disabled} required={required} className={className} checked={checked} onCheckedChange={onCheckedChange} name={name} value={value}/>;}
