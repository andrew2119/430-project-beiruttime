'use client';
import { useEffect, useRef, useState } from 'react';
import { Button } from '@beirut-time/ui';
import type { Photo } from '@contracts/contracts-catalog/discovery';
import { useLocale } from '@/shell/locale-context';
import en from './en.json';
import ar from './ar.json';

export function publicImageURL(url: string): string | null {
  // Public media is same-origin; never render an arbitrary/private evidence URL.
  if(!/^\/(?:demo\/watches\/[A-Za-z0-9_./-]+|api\/(?:web|mobile)\/v1\/catalog\/v1\/listings\/[A-Za-z0-9_-]+\/photos\/[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+)$/.test(url)||/[\\\s]/.test(url)||url.includes('..')||url.includes('?')||url.includes('#')||url.includes('%')) return null;
  return url;
}
export function PublicPhoto({photo,fallback,eager=false}:{photo:Photo|null;fallback:string;eager?:boolean}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [failed,setFailed]=useState(false), [decoded,setDecoded]=useState(false),[attempt,setAttempt]=useState(0);
  const url=photo&&publicImageURL(photo.url);
  useEffect(()=>{
    if(!failed||!url||attempt>=2)return;
    // CP F-48: shed-load/media failures get two bounded, jittered rereads, not
    // an invented missing-photo state or an unbounded background retry loop.
    const timer=setTimeout(()=>{setFailed(false);setDecoded(false);setAttempt(value=>value+1);},350+attempt*400+Math.random()*250);
    return ()=>clearTimeout(timer);
  },[failed,url,attempt]);
  const state=!photo?'missing':!url||failed?'unavailable':decoded?'ready':'loading';
  return <div className="discovery-photo" data-decoded={decoded} data-has-photo={!!photo} data-photo-state={state} aria-busy={state==='loading'}>
    {url&&!failed?/* CP F-48: reserve aspect before fetch, reveal only decoded pixels. */
      /* eslint-disable-next-line @next/next/no-img-element -- Public media already has a bounded, same-origin source policy. */
      <img key={attempt} src={url} alt={locale==='ar'&&photo!.alt_ar?photo!.alt_ar:photo!.alt} loading={eager?'eager':'lazy'} decoding="async" onLoad={event=>{const image=event.currentTarget;void image.decode().then(()=>{if(image.isConnected)setDecoded(true);},()=>{if(image.isConnected)setFailed(true);});}} onError={()=>setFailed(true)}/>:<span>{photo?t.photoUnavailable:fallback}</span>}
  </div>;
}
export function Gallery({photos,unavailable=false}:{photos:Photo[];unavailable?:boolean}) {
  const locale=useLocale(),t=locale==='ar'?ar:en, [selected,setSelected]=useState(0),dialog=useRef<HTMLDialogElement>(null);
  const photo=photos[selected]??null;
  function step(delta:number){setSelected(value=>(value+delta+photos.length)%photos.length);}
  return <section className="discovery-gallery" aria-label={t.photo}>
    <button className="discovery-hero-photo" type="button" aria-label={photo?t.zoom:unavailable?t.photoUnavailable:t.noPhoto} disabled={!photo} onClick={()=>dialog.current?.showModal()}><PublicPhoto key={photo?.id} photo={photo} fallback={unavailable?t.photoUnavailable:t.noPhoto} eager/>{photo&&<span className="discovery-zoom-label">{t.zoom} ↗</span>}</button>
    {photos.length>1&&<div className="discovery-thumbnails">{photos.map((item,index)=><button key={item.id} type="button" aria-label={`${t.photo} ${index+1}`} aria-pressed={selected===index} onClick={()=>setSelected(index)}><PublicPhoto photo={item} fallback={t.noPhoto}/></button>)}</div>}
    {photo?.credit&&<p className="discovery-help">{photo.credit}</p>}
    <dialog ref={dialog} className="discovery-zoom" aria-label={t.zoom} onClick={event=>{if(event.target===dialog.current)dialog.current.close();}}><div className="discovery-zoom-controls"><Button className="button-secondary" onClick={()=>dialog.current?.close()}>{t.close}</Button>{photos.length>1&&<><Button className="button-secondary" onClick={()=>step(-1)}>{t.previousPhoto}</Button><Button className="button-secondary" onClick={()=>step(1)}>{t.nextPhoto}</Button></>}</div><div className="discovery-zoom-scroll"><PublicPhoto key={photo?.id} photo={photo} fallback={t.noPhoto} eager/></div></dialog>
  </section>;
}
