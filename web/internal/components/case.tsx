import type { ReactNode } from 'react';
import { Card } from '@beirut-time/ui/foundation';
import type { ComponentId } from './model';
export function ComponentCase({id,title,children}: {id:ComponentId; title:string; children:ReactNode}) {
  return <Card className="bt-board-case"><section data-component={id} aria-labelledby={`${id}-title`}>
    <h2 id={`${id}-title`} className="bt-heading bt-board-case-title">{title}</h2><div className="bt-board-case-body">{children}</div>
  </section></Card>;
}
