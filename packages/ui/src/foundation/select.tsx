'use client';

import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import { Button } from './button';
import { description, Field } from './fields';
import { SelectCaption } from './select-caption';
import { State } from './state';
import { defaultSelectRuntime, gatedSelectRuntime } from './select-runtime';
import type { SelectEngagement, SelectProps } from './select-types';
export type { SelectOption, SelectProps, SelectMessages } from './select-types';

/** Intent warms code, not a mutation. The first frame stays the real named
 * trigger; it does not flash a different skeleton or load popup code eagerly. */
export function Select({id:supplied,label,hint,error,disabled,required,className,value,onValueChange,options,messages,name,searchable,loadGate}:SelectProps) {
  const generated = useId(), id = supplied ?? generated;
  const [delivery] = useState(()=>loadGate ? gatedSelectRuntime(loadGate) : defaultSelectRuntime);
  const [engagement,setEngagement] = useState<SelectEngagement|null>(null);
  const runtime = useSyncExternalStore(delivery.subscribe,delivery.current,delivery.server);
  const triggerRef = useRef<HTMLButtonElement|null>(null);
  useEffect(()=>{
    if (!engagement || runtime.component) return;
    const leave = (event:Event)=>{if (event.target instanceof Node && !triggerRef.current?.contains(event.target)) setEngagement(current=>current && (current.open || current.focus) ? {...current,open:false,focus:false} : current);};
    window.addEventListener('pointerdown',leave,true);window.addEventListener('focusin',leave,true);
    return ()=>{window.removeEventListener('pointerdown',leave,true);window.removeEventListener('focusin',leave,true);};
  },[engagement,runtime.component]);
  if (runtime.component && engagement) return <runtime.component id={id} label={label} hint={hint} error={error} disabled={disabled} required={required} className={className} value={value} onValueChange={onValueChange} options={options} messages={messages} name={name} searchable={searchable} engagement={engagement}/>;
  const text = options.find(option=>option.value === value)?.label ?? value ?? messages.placeholder;
  const engage = (open:boolean,input:'pointer'|'keyboard',edge:'first'|'last' = 'first') => {if (disabled) return;setEngagement({open,focus:true,input,edge});void delivery.load();};
  const waiting = !!engagement && runtime.status === 'loading';
  return <Field id={id} label={label} hint={hint} error={error} className={className}>
    {name && <input type="hidden" name={name} value={value ?? ''} disabled={disabled}/>}
    <Button ref={triggerRef} id={id} className="bt-select-trigger" variant="outline" role="combobox" aria-invalid={error ? true : undefined} aria-required={required} aria-haspopup="dialog" aria-expanded={false} aria-controls={`${id}-popup`} aria-busy={waiting || undefined} aria-describedby={description(id,hint,error)} aria-label={`${label}: ${text}`} disabled={disabled}
      onPointerEnter={()=>{if (!disabled) void delivery.load();}}
      onFocus={event=>{if (!engagement) engage(false,event.currentTarget.matches(':focus-visible') ? 'keyboard' : 'pointer');else void delivery.load();}}
      onPointerDown={event=>{if (event.button === 0 && !event.ctrlKey) {event.preventDefault();engage(true,'pointer');}}}
      onClick={event=>engage(true,event.detail === 0 ? 'keyboard' : 'pointer')}
      onKeyDown={event=>{
        if (event.key === 'Escape' && engagement) {event.preventDefault();setEngagement({...engagement,open:false});}
        if (['Enter',' ','ArrowDown','ArrowUp'].includes(event.key)) {event.preventDefault();engage(true,'keyboard',event.key === 'ArrowUp' ? 'last' : 'first');}
      }}><SelectCaption text={text}/></Button>
    {waiting && <span className="bt-sr-only" role="status">{messages.loading}</span>}
    {engagement && runtime.status === 'error' && <State kind="error" title={messages.errorTitle} body={messages.errorBody}><Button variant="outline" onClick={event=>{engage(true,event.detail === 0 ? 'keyboard' : 'pointer');triggerRef.current?.focus({preventScroll:true});}}>{messages.retry}</Button></State>}
  </Field>;
}
