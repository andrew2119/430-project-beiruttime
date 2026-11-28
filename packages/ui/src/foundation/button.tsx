'use client';

import type { FocusEventHandler, KeyboardEventHandler, MouseEventHandler, PointerEventHandler, ReactNode, Ref } from 'react';
import Link from 'next/link';
import { markMotionInput } from '../motion-tokens';
import { cn } from '../utils';

export type ButtonVariant = 'default' | 'outline' | 'ghost' | 'destructive';
export type ButtonSize = 'default' | 'sm' | 'icon';
type ActionProps = {
  children: ReactNode; className?: string; variant?: ButtonVariant; size?: ButtonSize;
  disabled?: boolean; busy?: boolean; success?: boolean; id?: string;
  'aria-label'?: string; 'aria-describedby'?: string; 'aria-expanded'?: boolean; 'aria-controls'?: string; 'aria-haspopup'?: 'dialog'|'menu'|'listbox'; 'aria-busy'?:boolean; 'aria-invalid'?:boolean; role?:'combobox'; 'aria-required'?:boolean; 'data-bt-motion-input'?: 'pointer'|'keyboard'|'none';
  onClick?: MouseEventHandler<HTMLButtonElement>; onKeyDown?: KeyboardEventHandler<HTMLButtonElement>;
  onPointerDown?: PointerEventHandler<HTMLButtonElement>; onPointerEnter?: PointerEventHandler<HTMLButtonElement>; onFocus?: FocusEventHandler<HTMLButtonElement>;
};

/** Semantic states change paint, never the label's box or its hit target. */
export function Button({children, className, variant = 'default', size = 'default', disabled, busy, success, id, type = 'button', name, value, form, ref, 'aria-label': label, 'aria-describedby': description, 'aria-expanded': expanded, 'aria-controls': controls, 'aria-haspopup': hasPopup, 'aria-busy': ariaBusy, 'aria-invalid': invalid, role, 'aria-required': ariaRequired, 'data-bt-motion-input': motionInput = 'none', onClick, onKeyDown, onPointerDown, onPointerEnter, onFocus}: ActionProps & {type?: 'button' | 'submit' | 'reset'; name?: string; value?: string; form?: string; ref?: Ref<HTMLButtonElement>}) {
  return <button ref={ref} id={id} type={type} name={name} value={value} form={form}
    disabled={disabled || busy} aria-busy={ariaBusy ?? (busy || undefined)} aria-invalid={invalid} aria-label={label} aria-describedby={description} aria-expanded={expanded} aria-controls={controls} aria-haspopup={hasPopup} role={role} aria-required={ariaRequired}
    data-variant={variant} data-size={size} data-busy={busy ? '' : undefined} data-success={success ? '' : undefined} data-bt-motion-input={motionInput}
    className={cn('bt-button bt-pressable', className)} onClick={onClick} onPointerEnter={onPointerEnter}
    onPointerDown={event => {markMotionInput(event.currentTarget, 'pointer'); onPointerDown?.(event);}}
    onKeyDown={event => {markMotionInput(event.currentTarget, 'keyboard'); onKeyDown?.(event);}}
    onFocus={event => {if (event.currentTarget.matches(':focus-visible')) markMotionInput(event.currentTarget, 'keyboard'); onFocus?.(event);}}>
    <span className="bt-button-label">{children}</span><span className="bt-button-progress" aria-hidden="true" /><span className="bt-button-result" aria-hidden="true">{success ? '✓' : null}</span>
  </button>;
}

export function ButtonLink({href, children, className, variant = 'default', size = 'default', disabled = false, prefetch, onClick, 'aria-current': current, 'aria-label': label}: {href:string; children:ReactNode; className?:string; variant?:ButtonVariant; size?:ButtonSize; disabled?:boolean; prefetch?:boolean; onClick?:MouseEventHandler<HTMLAnchorElement>; 'aria-current'?:'page'|'location'; 'aria-label'?:string}) {
  return <Link href={href} prefetch={disabled ? false : prefetch} aria-current={current} aria-label={label} aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : undefined}
    data-variant={variant} data-size={size} className={cn('bt-button bt-pressable', className)}
    onClick={event => {if (disabled) event.preventDefault(); else onClick?.(event);}}
    onPointerDown={event => markMotionInput(event.currentTarget, 'pointer')}
    onKeyDown={event => {markMotionInput(event.currentTarget, 'keyboard'); if (disabled && ['Enter',' '].includes(event.key)) event.preventDefault();}}>
    <span className="bt-button-label">{children}</span>
  </Link>;
}

export function buttonVariants() { return 'bt-button bt-pressable'; }
