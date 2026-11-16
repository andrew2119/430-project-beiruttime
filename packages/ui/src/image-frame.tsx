'use client';
/* eslint @next/next/no-img-element: "error" */
import { useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { cn } from './utils';

/** Reserve marketplace photo geometry and reveal only decoded pixels.
 * Photo source selection remains the caller's existing catalog policy. */
export function ImageFrame({ src, alt, width, height, placeholder, fallback, className, priority = false, ...props }: Omit<ComponentProps<'img'>, 'placeholder' | 'onLoad' | 'onError'> & { placeholder: ReactNode; fallback?: ReactNode; priority?: boolean }) {
  const [result, setResult] = useState<{ src: typeof src; state: 'loaded' | 'error' } | null>(null);
  const image = useRef<HTMLImageElement>(null);
  const state = !src ? 'placeholder' : result?.src === src ? result.state : 'loading';
  return <span className={cn('ui-image-frame', className)} data-image-state={state} data-image-reveal="late" style={{ aspectRatio: width && height ? `${width}/${height}` : undefined }}>
    {/* eslint-disable-next-line @next/next/no-img-element -- This shared frame owns reserved geometry and decode-gated catalog images. */}
    {src && <img {...props} ref={image} src={src} alt={alt} aria-hidden={state!=='loaded'||undefined} width={width} height={height} className="ui-image-frame-img" loading={priority ? 'eager' : 'lazy'} decoding="async" onLoad={async event => {
      const node = event.currentTarget;
      try { await node.decode(); if (image.current === node) setResult({ src, state: 'loaded' }); }
      catch { if (image.current === node) setResult({ src, state: 'error' }); }
    }} onError={() => setResult({ src, state: 'error' })} />}
    <span className="ui-image-frame-placeholder" aria-hidden={state === 'loaded' || undefined} role={state !== 'loaded' && alt ? 'img' : undefined} aria-label={state !== 'loaded' && alt ? alt : undefined}>{state === 'error' ? fallback ?? placeholder : placeholder}</span>
  </span>;
}
