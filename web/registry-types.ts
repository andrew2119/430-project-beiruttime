import type { ComponentType } from 'react';
import type { Locale } from '@beirut-time/i18n';
import type { ServiceName } from './lib/api/types';
export type Role = 'public' | 'buyer' | 'private_seller' | 'dealer' | 'brand' | 'operator';
export type Area = 'storefront' | 'account' | 'seller' | 'operator';
export type NavEntry = { id: string; href: string; label: Record<Locale,string>; order: number; area: Area; bottom?: boolean; roles: Role[] };
export type SlotContext = { locale: Locale; resourceId?: string; accessFingerprint?: string };
export type Registration = {
  lane: `L${string}`;
  namespace: string;
  routes: { path: string; roles: Role[]; area: Area }[];
  navigation?: NavEntry[];
  dictionaries: Record<Locale, Record<string, string>>;
  // Import the feature's own CSS from its registration; never edit root CSS.
  slots?: { id: string; target: 'watch.detail' | 'buyer.dashboard' | 'seller.dashboard' | 'operator.dashboard'; load: () => Promise<{ default: ComponentType<SlotContext> }> }[];
  gateway?: { service: ServiceName; path: string; methods: ('GET'|'POST'|'PATCH'|'PUT'|'DELETE')[]; roles: Role[]; forwardCookies?: string[]; maxBodyBytes?: number; maxResponseBytes?: number }[];
};
