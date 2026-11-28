'use client';

import { useLinkStatus } from 'next/link';
import { Home, Watch, Search, Building2, CircleDollarSign, SlidersHorizontal, Wrench, Info, Image, UserRound, ShieldCheck, Gavel, LayoutDashboard, ClipboardList, ShoppingBag, Inbox, CheckCheck, Settings, type LucideIcon } from 'lucide-react';

export type NavigationMotion = 'greet' | 'notice' | 'adjust' | 'wind' | 'reveal' | 'arrive' | 'hands' | 'strike' | 'lift' | 'balance' | 'confirm';
export const navigationIcons = {
  'auction-policy': {icon:Gavel, motion:'strike'},
  home: {icon:Home, motion:'greet'}, settings: {icon:Settings, motion:'wind'}, about: {icon:Info, motion:'notice'},
  account: {icon:UserRound, motion:'greet'}, 'private-verification': {icon:ShieldCheck, motion:'confirm'}, 'private-consent': {icon:CheckCheck, motion:'confirm'},
  'official-businesses': {icon:Building2, motion:'reveal'}, 'seller-listings': {icon:Watch, motion:'adjust'}, 'seller-dashboard': {icon:LayoutDashboard, motion:'balance'},
  'image-credits': {icon:Image, motion:'lift'}, watches: {icon:Watch, motion:'hands'}, search: {icon:Search, motion:'wind'},
  'seller-auctions': {icon:Gavel, motion:'strike'}, 'buyer-workspace': {icon:ShoppingBag, motion:'balance'}, 'exact-prices': {icon:CircleDollarSign, motion:'balance'},
  'private-inbox': {icon:Inbox, motion:'arrive'}, 'buying-readiness': {icon:CheckCheck, motion:'confirm'}, 'l08-checkout': {icon:ShoppingBag, motion:'reveal'},
  'l08-requests': {icon:ClipboardList, motion:'arrive'}, 'operator-desk': {icon:LayoutDashboard, motion:'notice'}, moderation: {icon:ShieldCheck, motion:'confirm'},
  'business-intake': {icon:Building2, motion:'reveal'}, 'brand-options': {icon:SlidersHorizontal, motion:'adjust'}, 'official-services': {icon:Wrench, motion:'wind'},
  'l13-withdrawals': {icon:ClipboardList, motion:'notice'},
  'brand-quotes': {icon:CircleDollarSign, motion:'balance'},
  offers: {icon:ShoppingBag, motion:'balance'},
  'repair-quotes': {icon:Wrench, motion:'adjust'},
  'brand-customizations': {icon:Wrench, motion:'adjust'},
} as const satisfies Record<string, {icon:LucideIcon; motion:NavigationMotion}>;
export type NavigationDestination = keyof typeof navigationIcons;

type NavigationIconProps = {
  id: NavigationDestination;
  active?: boolean;
  pending?: boolean;
  busy?: boolean;
  input?: 'pointer' | 'keyboard' | 'none';
  animateArrival?: boolean;
};
/** Static by default. Callers may opt into an occasional pointer arrival, never
 * keyboard or hover replay. Pending state does not block the navigation label. */
export function NavigationIcon({id, active = false, pending = false, busy = false, input = 'none', animateArrival = false}: NavigationIconProps) {
  const {icon:Icon, motion} = navigationIcons[id];
  const animate = input === 'pointer' && animateArrival;
  return <span className="bt-nav-icon" aria-hidden="true" data-motion={motion} data-active={active ? '' : undefined} data-pending={pending || busy ? '' : undefined} data-bt-animate={animate ? 'pointer' : undefined} data-bt-motion-input={input}>
    <Icon className="bt-nav-glyph" aria-hidden="true" />
  </span>;
}
export function PendingNavigationIcon({id, active = false, busy = false, input = 'none', animateArrival = false}: Omit<NavigationIconProps, 'pending'>) {
  const {pending} = useLinkStatus();
  return <NavigationIcon id={id} active={active} pending={pending} busy={busy} input={input} animateArrival={animateArrival} />;
}
