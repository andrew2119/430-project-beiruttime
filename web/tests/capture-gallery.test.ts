import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';

type Capture = { url: string; filename: string; viewport: string | number };
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const port = (url: string) => new URL(url).port;
const options = [undefined, '0', 'true', '1'];

// Evaluate only the real loop bodies. Browser/process startup is excluded, and
// the sandbox supplies no network, child-process or filesystem capabilities.
function loop(source: string, start: string, end?: string) {
  const from = source.indexOf(start);
  const to = end ? source.indexOf(end, from) : source.length;
  expect(from).toBeGreaterThanOrEqual(0);
  expect(to).toBeGreaterThan(from);
  return source.slice(from, to);
}

function verify(captures: Capture[], navigations: string[], appPort: string, galleryPorts: string[], appCount: number, enabled: boolean) {
  const app = captures.filter(capture => port(capture.url) === appPort);
  const gallery = captures.filter(capture => galleryPorts.includes(port(capture.url)));
  expect(app).toHaveLength(appCount);
  expect(gallery).toHaveLength(enabled ? 4 : 0);
  expect(captures).toHaveLength(appCount + (enabled ? 4 : 0));
  expect(new Set(captures.map(capture => capture.filename)).size).toBe(captures.length);
  expect(new Set(navigations.map(port))).toEqual(new Set([appPort, ...(enabled ? galleryPorts : [])]));
  expect(navigations.filter(url => galleryPorts.includes(port(url)))).toHaveLength(enabled ? 4 : 0);
  expect(app.filter(capture => String(capture.viewport).startsWith('1440'))).toHaveLength(appCount / 2);
  expect(app.filter(capture => String(capture.viewport).startsWith('390'))).toHaveLength(appCount / 2);
}

describe('Gallery capture is explicitly opt-in', () => {
  it.each(options)('business capture with BT_CAPTURE_GALLERY=%s', async galleryOption => {
    const source = read('../features/business/proof/capture.mjs');
    const routes = source.match(/^const routes=.*$/m)?.[0];
    expect(routes).toBeDefined();
    const code = `${routes}\n${loop(source, 'for(const [size,viewport]')}`;
    const navigations: string[] = [];
    const captures: Capture[] = [];
    let viewport = '';
    await runInNewContext(`(async () => {${code}})()`, {
      process: { env: { BT_CAPTURE_GALLERY: galleryOption } },
      shots: 'memory-only',
      cli: async (_command: string, _option: string, value: string) => { viewport = value; },
      run: async (script: string) => {
        await runInNewContext(`(async () => {${script}})()`, {
          page: {
            open: async (url: string) => { navigations.push(url); },
            eval: async () => true,
            wait: async () => {},
            fill: async () => {},
            click: async () => {},
          },
        }, { timeout: 1000 });
      },
      screenshot: async (url: string, filename: string) => { captures.push({ url, filename, viewport }); },
      console: { log() {} },
    }, { timeout: 1000 });
    verify(captures, navigations, '3357', ['3352', '3353'], 72, galleryOption === '1');
    if (galleryOption === '1') {
      expect(captures.filter(capture => port(capture.url) !== '3357').map(capture => capture.filename)).toEqual([
        'memory-only/reference-controls-desktop-light.png', 'memory-only/reference-controls-desktop-dark.png',
        'memory-only/reference-controls-phone-light.png', 'memory-only/reference-controls-phone-dark.png',
      ]);
    }
  });

  it.each(options)('buyer capture with BT_CAPTURE_GALLERY=%s', async galleryOption => {
    const source = read('../features/proxy-bid/capture-shots.mjs');
    const code = loop(source, '  const routes=', '\n} finally');
    const navigations: string[] = [];
    const captures: Capture[] = [];
    const readiness: string[] = [];
    const cookies: Record<string, unknown>[] = [];
    let viewport = 0;
    let currentUrl = '';
    let screenshotCalls = 0;
    await runInNewContext(`(async () => {${code}})()`, {
      process: { env: { BT_CAPTURE_GALLERY: galleryOption } },
      call: async (method: string, params: Record<string, unknown>) => {
        if (method === 'Emulation.setDeviceMetricsOverride') viewport = Number(params.width);
        if (method === 'Page.navigate') { currentUrl = String(params.url); navigations.push(currentUrl); }
        if (method === 'Network.setCookie') cookies.push(params);
        if (method === 'Page.captureScreenshot') screenshotCalls++;
        return { data: '' };
      },
      waitFor: async (expression: string) => { readiness.push(expression); },
      evaluate: async (expression: string) => { expect(expression).toBe('innerWidth'); return viewport; },
      writeFile: async (filename: string) => { captures.push({ url: currentUrl, filename, viewport }); },
      join, shots: 'memory-only', Buffer,
      setTimeout: (resolve: () => void) => resolve(),
      console: { log() {} },
    }, { timeout: 1000 });
    verify(captures, navigations, '33517', ['33515'], 56, galleryOption === '1');
    expect(navigations[0]).toBe('http://127.0.0.1:33517/en/buyer');
    expect(screenshotCalls).toBe(captures.length);
    expect(cookies).toHaveLength(galleryOption === '1' ? 8 : 4);
    expect(cookies.every(cookie => cookie.name === 'bt-theme' && ['light', 'dark'].includes(String(cookie.value)))).toBe(true);
    expect(readiness.filter(expression => expression.includes('.ph-card-title'))).toHaveLength(galleryOption === '1' ? 4 : 0);
    expect(readiness.every(expression => expression.includes('document.documentElement.dataset.theme==='))).toBe(true);
    if (galleryOption === '1') {
      expect(captures.slice(56).map(capture => capture.filename)).toEqual([
        'memory-only/reference-en-light-desktop.png', 'memory-only/reference-en-light-phone.png',
        'memory-only/reference-en-dark-desktop.png', 'memory-only/reference-en-dark-phone.png',
      ]);
    }
  });
});
