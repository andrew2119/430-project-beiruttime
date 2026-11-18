'use client';

import { createContext, useContext, type ReactNode } from 'react';
import * as Primitive from '@radix-ui/react-direction';
const Context = createContext<'ltr'|'rtl'>('ltr');
/** Direction travels through portals as context, not just DOM inheritance. */
export function DirectionProvider({dir,children}: {dir:'ltr'|'rtl'; children:ReactNode}) {return <Context value={dir}><Primitive.Provider dir={dir}>{children}</Primitive.Provider></Context>;}
export function useDirection() {const dir = useContext(Context); return {dir,lang:dir === 'rtl' ? 'ar' : 'en'} as const;}
