'use client';

import { useState } from 'react';
import { Button, ImageFrame, Segmented } from '@beirut-time/ui/foundation';
import { Watch } from 'lucide-react';
import { MEDIA } from '../../tests/fixtures/worst-case';
import type { BoardCopy } from './copy';
export function MediaLifecycle({copy}: {copy:BoardCopy}) {
  const [source,setSource] = useState('first'), [revision,setRevision] = useState(0);
  const src = source === 'first' ? '/demo/watches/omega-x33-mars.jpg' : source === 'second' ? '/demo/watches/seiko-5.jpg' : source === 'broken' ? MEDIA.broken.url : undefined;
  return <section className="bt-board-stack" data-review-example="image-lifecycle">
    <Segmented label={copy.headings.image} value={source} onValueChange={setSource} options={[{value:'first',label:copy.photoFirst},{value:'second',label:copy.photoSecond},{value:'missing',label:copy.photoNone},{value:'broken',label:copy.photoBroken}]}/>
    <Button variant="outline" onClick={()=>setRevision(value=>value+1)}>{copy.remount}</Button>
    <ImageFrame key={revision} src={src} alt={source === 'missing' ? copy.imagePlaceholder : copy.imageAlt} width={480} height={360} placeholder={<Watch className="bt-media-glyph" aria-hidden="true"/>} fallback={<span className="bt-text">{copy.imageBroken}</span>}/>
    <div className="bt-board-image-grid"><div><h3 className="bt-heading">{copy.panorama}</h3><ImageFrame src="/demo/watches/review-panorama.svg" alt={copy.panoramaAlt} width={480} height={360} placeholder={<Watch className="bt-media-glyph" aria-hidden="true"/>}/></div><div><h3 className="bt-heading">{copy.portrait}</h3><ImageFrame src="/demo/watches/review-portrait.svg" alt={copy.portraitAlt} width={480} height={360} placeholder={<Watch className="bt-media-glyph" aria-hidden="true"/>}/></div></div>
  </section>;
}
