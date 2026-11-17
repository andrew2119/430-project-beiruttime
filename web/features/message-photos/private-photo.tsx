'use client';
import { useEffect, useRef, useState } from 'react';
import { State } from '@beirut-time/ui/foundation';
/** Private pixels stay in memory. No downloadable source or cacheable image URL. */
export function PrivatePhoto({ bytes, label, unavailable }: { bytes: Blob; label: string; unavailable: string }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    const node = canvas.current;
    createImageBitmap(bytes).then(image => {
      if (active && node) {
        node.width = image.width; node.height = image.height;
        node.getContext('2d')?.drawImage(image, 0, 0);
      }
      image.close();
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; if (node) { node.width = 0; node.height = 0; } };
  }, [bytes]);
  return failed ? <State kind="error" title={unavailable} body={unavailable}/> : <canvas className="l25-private-photo" ref={canvas} role="img" aria-label={label}/>;
}
