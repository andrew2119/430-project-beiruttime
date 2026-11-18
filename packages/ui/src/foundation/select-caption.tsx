import { ChevronDown } from 'lucide-react';
/** Static and engaged triggers share exactly the same value and icon boxes. */
export function SelectCaption({text}: {text:string}) {return <><span className="bt-select-value">{text}</span><ChevronDown className="bt-select-caret" aria-hidden="true"/></>;}
