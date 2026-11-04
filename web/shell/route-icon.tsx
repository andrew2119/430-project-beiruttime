'use client';
import { useLinkStatus } from 'next/link';
import { Home, Watch, Search, Building2, CircleDollarSign, SlidersHorizontal, Wrench, Info, Image, UserRound, ShieldCheck, Gavel, LayoutDashboard, ClipboardList, ShoppingBag, Inbox, CheckCheck, Settings, type LucideIcon } from 'lucide-react';
const icons: Record<string, LucideIcon> = { home: Home, watches: Watch, search: Search, business: Building2, prices: CircleDollarSign, customize: SlidersHorizontal, services: Wrench, about: Info, 'image-credits': Image, account: UserRound, buying: ShoppingBag, buyer: Gavel, inbox: Inbox, consent: CheckCheck };
export function RouteIcon({ id, href = '', active = false, pending = false }: { id: string; href?: string; active?: boolean; pending?: boolean }) {
  const pathIcon=icons[href.split('/')[1]] ?? (href==='/settings'?Settings:undefined);
  const Icon = icons[id] ?? pathIcon ?? (href.includes('verification') ? ShieldCheck : href.includes('auction') ? Gavel : href.includes('dashboard') ? LayoutDashboard : href.includes('listing') ? Watch : ClipboardList);
  return <span className="pg-nav-icon" data-motion={href.includes('auction') ? 'stamp' : 'pulse'} data-active={active ? '' : undefined} data-pending={pending ? '' : undefined}><Icon className="pg-nav-icon-glyph" aria-hidden="true"/></span>;
}
export function PendingRouteIcon(props: { id: string; href?: string; active?: boolean }) {
  const { pending } = useLinkStatus();
  return <RouteIcon {...props} pending={pending}/>;
}
