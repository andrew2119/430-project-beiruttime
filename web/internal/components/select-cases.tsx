'use client';

import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { Button, Select, type SelectOption } from '@beirut-time/ui/foundation';
import type { BoardCopy } from './copy';
import { createDeliveryGate } from './select-delivery';
/** This controls actual shared code readiness, not an invented market answer. */
export function SelectDeliveryCase({copy,options}: {copy:BoardCopy;options:readonly SelectOption[]}) {
  const [gate] = useState(createDeliveryGate), [value,setValue] = useState<string|null>(null), id = useId();
  const phase = useSyncExternalStore(gate.subscribe,gate.current,gate.server);
  useEffect(()=>()=>gate.dispose(),[gate]);
  return <section className="bt-board-stack" data-review-example="select-delivery"><h3 className="bt-heading">{copy.deliveryTitle}</h3><p className="bt-text">{copy.deliveryHint}</p>
    <Select id={id} label={copy.select.placeholder} value={value} onValueChange={setValue} options={options} messages={copy.select} searchable loadGate={gate.wait}/>
    <div className="bt-board-row"><Button variant="outline" onClick={()=>document.getElementById(id)?.focus({preventScroll:true})}>{copy.deliveryStart}</Button><Button variant="outline" disabled={phase !== 'waiting'} onClick={gate.fail}>{copy.deliveryFail}</Button><Button variant="outline" disabled={phase !== 'waiting'} onClick={gate.release}>{copy.deliveryRelease}</Button></div>
    {phase !== 'idle' && phase !== 'closed' && <p className="bt-text" role="status">{phase === 'waiting' ? copy.deliveryWaiting : phase === 'failed' ? copy.deliveryFailed : copy.deliveryDone}</p>}
  </section>;
}
