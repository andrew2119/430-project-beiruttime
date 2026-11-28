'use client';

import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { AnimatedList, Badge, Button, Card, State, WatchImage, formatAmount, formatCount, formatNumber } from '@beirut-time/ui/foundation';
import { readMotionToken } from '@beirut-time/ui/motion';
import type { WatchSummary } from '@contracts/contracts-catalog/discovery';
import type { ReviewDataMode } from '../../tests/fixtures/worst-case';
import { ComponentCase } from './case';
import type { BoardCopy } from './copy';
import { boardData, pageOf, type BoardLocale } from './model';
function WatchExample({item,locale,copy}: {item:WatchSummary;locale:BoardLocale;copy:BoardCopy}) {
  return <Card className="bt-board-watch"><WatchImage src={item.thumbnail?.url} alt={(locale === 'ar' ? item.thumbnail?.alt_ar : item.thumbnail?.alt) || copy.imagePlaceholder}/><div className="bt-board-stack"><h3 className="bt-heading">{item.title}</h3><p className="bt-text">{item.brand} · {item.model}</p><p className="bt-text">{item.location}</p><bdi className="bt-number" dir="ltr">{formatAmount(item.price?.amount,locale,item.price?.currency ?? '',copy.missing)}</bdi><Badge>{copy.demoBadge}</Badge></div></Card>;
}
type LiveRow = {id:string;label:string};
function LiveRows({copy,locale,scope}: {copy:BoardCopy;locale:BoardLocale;scope:string}) {
  const [rows,setRows] = useState<LiveRow[]>([{id:'first',label:copy.liveRow}]), [removed,setRemoved] = useState<LiveRow|null>(null), [input,setInput] = useState<'pointer'|'keyboard'>('keyboard');
  const serial = useRef(0), timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  useEffect(()=>{const pending = timers.current;return ()=>{for (const timer of pending) clearTimeout(timer);};},[]);
  const nextRow = () => ({id:`live-${++serial.current}`,label:copy.liveRow});
  const mode = (event:MouseEvent<HTMLButtonElement>)=>{const value = event.detail > 0 ? 'pointer' : 'keyboard';setInput(value);return value;};
  const later = (duration:number,run:()=>void)=>{if (!duration) {run();return;}const timer = setTimeout(()=>{timers.current.delete(timer);run();},duration);timers.current.add(timer);};
  return <div className="bt-board-stack"><p className="bt-text">{copy.motionHint}</p><div className="bt-board-row">
    <Button variant="outline" onClick={event=>{mode(event);setRows(current=>[...current,nextRow()]);}}>{copy.addRow}</Button>
    <Button variant="outline" disabled={!rows.length} onClick={event=>{mode(event);setRemoved(rows[0]);setRows(current=>current.slice(1));}}>{copy.removeRow}</Button>
    <Button variant="outline" disabled={!removed} onClick={event=>{mode(event);if (removed) setRows(current=>current.some(row=>row.id === removed.id) ? current : [removed,...current]);setRemoved(null);}}>{copy.undo}</Button>
    <Button variant="outline" disabled={rows.length < 2} onClick={event=>{mode(event);setRows(current=>[...current].reverse());}}>{copy.reverse}</Button>
    <Button variant="outline" onClick={event=>{const value = mode(event), row = nextRow(), duration = value === 'pointer' ? readMotionToken('--bt-motion-image',event.currentTarget) ?? 0 : 0;setRows(current=>[...current,row]);later(duration/2,()=>setRows(current=>current.filter(item=>item.id !== row.id)));}}>{copy.removeMidway}</Button>
    <Button variant="outline" disabled={!rows.length} onClick={event=>{const value = mode(event), row = rows[0], duration = value === 'pointer' ? readMotionToken('--bt-motion-exit',event.currentTarget) ?? 0 : 0;setRows(current=>current.filter(item=>item.id !== row.id));later(duration/2,()=>setRows(current=>current.some(item=>item.id === row.id) ? current : [row,...current]));}}>{copy.undoMidway}</Button>
  </div><AnimatedList scopeKey={scope} items={rows} getKey={row=>row.id} enters={()=>true} input={input} empty={<State headingLevel={3} title={copy.emptyTitle} body={copy.emptyBody}/>}>
    {(row,index)=><Card><p className="bt-text">{row.label} <bdi>{formatNumber(index+1,locale)}</bdi></p></Card>}
  </AnimatedList></div>;
}
export function DataCases({mode,locale,copy}: {mode:ReviewDataMode;locale:BoardLocale;copy:BoardCopy}) {
  const items = useMemo(()=>boardData(mode),[mode]), [requested,setRequested] = useState(0), page = pageOf(items,requested);
  return <ComponentCase id="list" title={copy.headings.list}><div id="data-preview" className="bt-board-stack"><p className="bt-text">{formatCount(page.total,locale,copy.counts,copy.missing)} · {copy.records}</p><div className="bt-board-row"><Button variant="outline" disabled={page.page === 0} onClick={()=>setRequested(page.page-1)}>{copy.previous}</Button><p className="bt-number" role="status">{copy.page} {formatNumber(page.page+1,locale)} {copy.of} {formatNumber(page.pages,locale)}</p><Button variant="outline" disabled={page.page+1 === page.pages} onClick={()=>setRequested(page.page+1)}>{copy.next}</Button></div>
    <AnimatedList scopeKey={`${mode}:${page.page}`} items={page.items} getKey={item=>item.id} grid empty={<State headingLevel={3} title={copy.emptyTitle} body={copy.emptyBody}/>}>
      {item=><WatchExample item={item} locale={locale} copy={copy}/>}
    </AnimatedList><LiveRows key={`${mode}:${locale}`} scope={`live:${mode}:${locale}`} copy={copy} locale={locale}/>
  </div></ComponentCase>;
}
