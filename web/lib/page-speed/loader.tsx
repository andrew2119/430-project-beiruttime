'use client';
import dynamic from 'next/dynamic';
/** The warming controller/table is not part of a page's first-frame work. */
const DeferredPageWarming = dynamic(()=>import('./mount').then(module=>module.PageWarmingMount),{ssr:false});
export function PageWarmingLoader() {return <DeferredPageWarming/>;}
