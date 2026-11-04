import type { ReactNode, Ref } from 'react';
import { Card } from './card';
/** CP's public AuthCard, with a watch-marketplace mark and caller-owned heading level. */
export function AuthCard({ title, headingRef, authenticated = false, children, subtitle, titleAs: Title = 'h2' }: {
  title: string; headingRef?: Ref<HTMLHeadingElement>; authenticated?: boolean; children: ReactNode; subtitle?: string; titleAs?: 'h1' | 'h2';
}) {
  if (authenticated) return <Card><Title ref={headingRef} tabIndex={-1}>{title}</Title>{children}</Card>;
  return <section className="pg-auth-card"><div className="pg-auth-head"><div className="pg-auth-mark" aria-hidden="true">BT</div><Title className="pg-auth-title" ref={headingRef} tabIndex={-1}>{title}</Title>{subtitle && <p className="pg-auth-subtitle">{subtitle}</p>}</div>{children}</section>;
}
