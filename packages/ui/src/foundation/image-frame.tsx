'use client';

import { useCallback, useRef, useState, type ReactNode } from 'react';
import { Watch } from 'lucide-react';
import { cn } from '../utils';
import { initialsOf, usableImageSource } from './initials';
import { decodeFrame, type FrameAnswer } from './image-decode';
/* eslint @next/next/no-img-element: "error" */

export type ImageFrameProps = {src?:string|null; alt:string; width:number; height:number; placeholder:ReactNode; fallback?:ReactNode; priority?:boolean; className?:string};
export function ImageFrame({src, alt, width, height, placeholder, fallback, priority = false, className}: ImageFrameProps) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) throw new RangeError('Image dimensions must be finite and positive.');
  const source = usableImageSource(src);
  return <FrameSource key={source ?? ''} src={source} alt={alt} width={width} height={height} placeholder={placeholder} fallback={fallback} priority={priority} className={className}/>;
}
/** The complete loading/error state belongs to this keyed pixel generation. */
function FrameSource({src:source,alt,width,height,placeholder,fallback,priority,className}:ImageFrameProps) {
  const node = useRef<HTMLImageElement|null>(null), decoding = useRef<{image:HTMLImageElement;work:Promise<void>}|null>(null);
  const [answer, setAnswer] = useState<FrameAnswer|null>(null);
  const ready = !!source && answer?.src === source && answer.state === 'ready';
  const failed = !!source && answer?.src === source && answer.state === 'error';
  const reveal = useCallback((image:HTMLImageElement,instant:boolean) => {
    if (decoding.current?.image === image) return decoding.current.work;
    const work = decodeFrame(image,source ?? '',instant,()=>node.current === image,setAnswer);
    decoding.current = {image,work};return work;
  },[source]);
  const attach = useCallback((image:HTMLImageElement | null) => {
    node.current = image;
    if (image?.complete) {if (image.naturalWidth > 0) void reveal(image,true);else setAnswer({src:source ?? '',state:'error'});}
  }, [reveal,source]);
  return <span className={cn('bt-image-frame', className)} style={{aspectRatio:`${width} / ${height}`, maxWidth:width}} role={alt ? 'img' : undefined} aria-label={alt || undefined} data-image-state={ready ? 'ready' : failed ? 'error' : source ? 'loading' : 'placeholder'}>
    {source && !failed && (
      // eslint-disable-next-line @next/next/no-img-element -- This reserved frame alone gates whole-picture reveal on decode and owns native delivery attributes.
      <img key={source} ref={attach} src={source} alt="" width={width} height={height} decoding="async" loading={priority ? 'eager' : 'lazy'} fetchPriority={priority ? 'high' : undefined} draggable={false}
        className="bt-image-pixels" data-ready={ready ? '' : undefined} data-instant={ready && answer?.instant ? '' : undefined}
        onLoad={event => {void reveal(event.currentTarget, false);}} onError={event => {if (node.current === event.currentTarget) setAnswer({src:source, state:'error'});}} />
    )}
    <span className="bt-image-placeholder" aria-hidden="true" data-hidden={ready ? '' : undefined} data-instant={ready && answer?.instant ? '' : undefined}>{failed ? fallback ?? placeholder : placeholder}</span>
  </span>;
}
export function Avatar({name, label, src, size = 'default'}: {name:string; label:string; src?:string|null; size?:'compact'|'default'|'large'}) {
  const initials = initialsOf(name), pixels = size === 'compact' ? 24 : size === 'large' ? 64 : 40;
  return <span className="bt-avatar" data-size={size}><ImageFrame src={src} alt={label} width={pixels} height={pixels}
    placeholder={<span className="bt-avatar-initials"><span>{initials[0] ?? '–'}{initials[1] && <span className="bt-avatar-last">{initials[1]}</span>}</span></span>} /></span>;
}
export function WatchImage({src, alt, priority = false}: {src?:string|null; alt:string; priority?:boolean}) {
  return <ImageFrame src={src} alt={alt} width={480} height={360} priority={priority} placeholder={<Watch className="bt-media-glyph" aria-hidden="true"/>}/>;
}
