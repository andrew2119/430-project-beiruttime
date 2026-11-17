'use client';

import { useId, useRef, useState } from 'react';
import { Button, Checkbox, DirectionProvider, Segmented, Toaster } from '@beirut-time/ui/foundation';
import type { ReviewDataMode } from '../../tests/fixtures/worst-case';
import { ThemeSwitch } from '@/shell/theme-switch';
import { NavigationIcon, navigationIcons, type NavigationDestination } from '@/shell/navigation-icon';
import { BasicCases } from './basic-cases';
import { SurfaceCases } from './surface-cases';
import { DataCases } from './data-cases';
import { ComponentCase } from './case';
import { COPY } from './copy';
import { boardBoundary } from './boundary';
import { DATA_MODES, persistBoard, reviewLocale, reviewMode, type BoardLocale } from './model';
export function ComponentBoard({initialMode,initialLocale}: {initialMode:ReviewDataMode;initialLocale:BoardLocale}) {
  const [mode,setMode] = useState(initialMode), [locale,setLocale] = useState(initialLocale), [narrow,setNarrow] = useState(false);
  const [arrival,setArrival] = useState<{revision:number;input:'pointer'|'keyboard'}>({revision:0,input:'keyboard'});
  const contentRef = useRef<HTMLDivElement|null>(null), heading = useId(), copy = COPY[locale], example = boardBoundary(mode,locale);
  return <DirectionProvider dir={locale === 'ar' ? 'rtl' : 'ltr'}><section ref={contentRef} className="bt-board" dir={locale === 'ar' ? 'rtl' : 'ltr'} lang={locale} aria-labelledby={heading}>
    <header className="bt-board-header"><h1 id={heading} className="bt-heading">{copy.title}</h1><p className="bt-text">{copy.intro}</p><p className="bt-caption">{copy.demo}</p>
      <Segmented label={copy.language} locale={locale} value={locale} onValueChange={value=>{const next = reviewLocale(value);setLocale(next);persistBoard(mode,next);}} options={[{value:'en',label:'English'},{value:'ar',label:'العربية'}]}/>
      <Segmented label={copy.data} locale={locale} value={mode} onValueChange={value=>{const next = reviewMode(value);setMode(next);persistBoard(next,locale);}} options={DATA_MODES.map(value=>({value,label:copy.modes[value]}))}/>
      <Checkbox label={copy.narrow} checked={narrow} onCheckedChange={setNarrow} hint={copy.narrowHint}/>
    </header>
    <div className="bt-board-examples" data-narrow={narrow ? '' : undefined}>
      <BasicCases mode={mode} locale={locale} copy={example.copy}/><SurfaceCases key={`${mode}:${locale}`} mode={mode} copy={example.copy} locale={locale}/><DataCases mode={mode} locale={locale} copy={example.copy}/>
      <ComponentCase id="theme" title={copy.headings.theme}><ThemeSwitch lightLabel={example.copy.light} darkLabel={example.copy.dark}/></ComponentCase>
      <ComponentCase id="navigation" title={copy.headings.navigation}><p className="bt-text">{copy.motionHint}</p><Button variant="outline" onClick={event=>setArrival(current=>({revision:current.revision+1,input:event.detail > 0 ? 'pointer' : 'keyboard'}))}>{example.copy.playIcon}</Button><div className="bt-board-icon-grid">{(Object.keys(navigationIcons) as NavigationDestination[]).map(id=><span key={`${id}:${arrival.revision}`} className="bt-board-icon-example"><NavigationIcon id={id} input={arrival.input} animateArrival={arrival.revision > 0}/><span className="bt-caption" dir="ltr">{id}</span></span>)}</div><div className="bt-board-row"><span className="bt-board-icon-example"><NavigationIcon id="home" active/><span className="bt-caption">{copy.activeIcon}</span></span><span className="bt-board-icon-example"><NavigationIcon id="watches" pending/><span className="bt-caption">{copy.pendingIcon}</span></span><span className="bt-board-icon-example"><NavigationIcon id="settings" busy/><span className="bt-caption">{copy.busy}</span></span></div></ComponentCase>
    </div>
    <Toaster label={example.copy.toastRegion} dismissLabel={example.copy.dismissToast} contentRef={contentRef}/>
  </section></DirectionProvider>;
}
