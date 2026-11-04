import type { ReactNode } from 'react';
/** Composition frames, not authorization guards. Identity owns the session boundary. */
export function StorefrontLayout({ children }: { children: ReactNode }) { return <div className="layout-storefront">{children}</div>; }
export function AccountLayout({ children }: { children: ReactNode }) { return <div className="layout-account">{children}</div>; }
export function SellerLayout({ children }: { children: ReactNode }) { return <div className="layout-seller">{children}</div>; }
export function OperatorLayout({ children }: { children: ReactNode }) { return <div className="layout-operator">{children}</div>; }
