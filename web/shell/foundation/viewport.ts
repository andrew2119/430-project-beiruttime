/** Cap the CSS dvh frame to the unzoomed visual viewport while a keyboard or
 * browser bar takes space. This is measured layout, never authored motion;
 * zoom keeps its native canvas and the previous inline cap is restored. */
export function fitVisualViewport(element:HTMLElement,view:Window = window) {
  const viewport = view.visualViewport, prior = element.style.maxBlockSize;
  if (!viewport) return ()=>{};
  const fit = ()=>{
    const height = Math.min(viewport.height,view.innerHeight);
    element.style.maxBlockSize = viewport.scale === 1 && Number.isFinite(height) && height > 0 ? `${height}px` : prior;
  };
  viewport.addEventListener('resize',fit);view.addEventListener('resize',fit);fit();
  return ()=>{viewport.removeEventListener('resize',fit);view.removeEventListener('resize',fit);element.style.maxBlockSize = prior;};
}
