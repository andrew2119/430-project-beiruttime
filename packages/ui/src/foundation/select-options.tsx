'use client';

import { useCallback, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { nextChoice } from './choice';
import { useDirection } from './direction';
import { description, Field, Input } from './fields';
import { Popover, PopoverContent, PopoverTrigger } from './popover';
import { SelectCaption } from './select-caption';
import { filterSelectOptions, matchingChoice } from './select-model';
import { State } from './state';
import type { SelectImplementationProps } from './select-types';
const TYPEAHEAD_WINDOW_MS = 700;

export function SelectOptions({id,label,hint,error,disabled,required,className,value,onValueChange,options,messages,name,searchable,engagement}:SelectImplementationProps) {
  const [open,setOpen] = useState(engagement.open && !disabled), [query,setQuery] = useState(''), [edge,setEdge] = useState(engagement.edge);
  const searchRef = useRef<HTMLInputElement|null>(null), listRef = useRef<HTMLDivElement|null>(null);
  const typeahead = useRef({text:'',at:0});
  const direction = useDirection(), showSearch = searchable ?? options.length > 8;
  const filtered = filterSelectOptions(options,query,direction.lang), text = options.find(option=>option.value === value)?.label ?? value ?? messages.placeholder;
  if (new Set(options.map(option=>option.value)).size !== options.length) throw new Error('Select option values must be unique.');
  if (disabled && open) setOpen(false);
  const attachTrigger = useCallback((node:HTMLButtonElement|null)=>{if (node && engagement.focus) node.focus({preventScroll:true});},[engagement.focus]);
  const selected = filtered.findIndex(option=>option.value === value && !option.disabled), first = filtered.findIndex(option=>!option.disabled);
  const focusOption = (index:number) => {const node = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]')[index];node?.focus({preventScroll:true});node?.scrollIntoView({block:'nearest',inline:'nearest'});};
  return <Field id={id} label={label} hint={hint} error={error} className={className}>
    {name && <input type="hidden" name={name} value={value ?? ''} disabled={disabled}/>}
    <Popover open={open} initialInput={engagement.input} onOpenChange={next=>{setOpen(next);if (!next) setQuery('');}}>
      <PopoverTrigger ref={attachTrigger} id={id} role="combobox" required={required} invalid={error ? true : undefined} controls={`${id}-popup`} describedBy={description(id,hint,error)} label={`${label}: ${text}`} disabled={disabled} className="bt-select-trigger"
        onKeyDown={event=>{if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {event.preventDefault();setEdge(event.key === 'ArrowUp' ? 'last' : 'first');setOpen(true);}}}><SelectCaption text={text}/></PopoverTrigger>
      <PopoverContent id={`${id}-popup`} label={label} closeLabel={messages.close} align="start" className="bt-select-popup" onOpenAutoFocus={event=>{
        event.preventDefault();
        if (showSearch) searchRef.current?.focus({preventScroll:true});
        else focusOption(selected < 0 ? nextChoice(filtered.map(option=>!!option.disabled),first,edge === 'last' ? 'End' : 'Home',direction.dir === 'rtl') : selected);
      }}>
        {showSearch && <Input ref={searchRef} id={`${id}-filter`} label={messages.filter} type="search" value={query} onValueChange={setQuery} onKeyDown={event=>{
          if (event.key === 'Escape') return;
          event.stopPropagation();
          if (event.key === 'ArrowDown') {event.preventDefault();focusOption(first);}
        }}/>}
        {filtered.length ? <div ref={listRef} role="listbox" aria-label={label} className="bt-select-options">
          {filtered.map((option,index)=><button key={option.value} type="button" role="option" aria-selected={option.value === value} disabled={option.disabled} tabIndex={index === (selected < 0 ? first : selected) ? 0 : -1}
            className="bt-menu-item bt-select-option" onClick={()=>{onValueChange(option.value);setOpen(false);setQuery('');}}
            onKeyDown={event=>{
              if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) {event.preventDefault();focusOption(nextChoice(filtered.map(item=>!!item.disabled),index,event.key,direction.dir === 'rtl'));}
              else if (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.altKey && !event.metaKey) {
                const now = event.timeStamp, previous = typeahead.current;
                const character = event.key.toLocaleLowerCase(direction.lang);
                const prefix = now-previous.at > TYPEAHEAD_WINDOW_MS || previous.text === character ? character : previous.text+character;
                typeahead.current = {text:prefix,at:now};
                const match = matchingChoice(filtered,prefix,index,direction.lang);if (match >= 0) {event.preventDefault();focusOption(match);}
              }
            }}><span className="bt-menu-label-copy">{option.label}</span><span className="bt-select-check" aria-hidden="true">{option.value === value && <Check/>}</span></button>)}
        </div> : <State headingLevel={3} title={messages.emptyTitle} body={messages.emptyBody}/>}
      </PopoverContent>
    </Popover>
  </Field>;
}
