'use client';
import { useCallback, type ReactNode } from 'react';
import { usePageReadScope } from './provider';
/** One real answer arrival per view/access, not per refresh/filter/render. The
 * shared CSS owns the fade and the keyboard/reduced-motion floor. */
export function AnswerArrival({view,children}: {view:string;children:ReactNode}) {
  const scope = usePageReadScope();
  const attach = useCallback((node:HTMLDivElement|null)=>{if (node && scope.claimArrival(view)) node.setAttribute('data-bt-arrival','');},[scope,view]);
  return <div ref={attach} className="bt-arrive" data-page-answer="" data-bt-motion-input={scope.input}>{children}</div>;
}
