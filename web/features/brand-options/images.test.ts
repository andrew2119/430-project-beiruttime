import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readPrivatePng } from './images';
class Reader {
  static LOADING = 1;
  static instances: Reader[] = [];
  readyState = 0;
  result: string | null = null;
  onload: (()=>void) | null = null;
  onerror: (()=>void) | null = null;
  onabort: (()=>void) | null = null;
  aborted = false;
  constructor() {Reader.instances.push(this);}
  readAsDataURL() {this.readyState=1;}
  abort() {this.aborted=true;this.readyState=2;this.onabort?.();}
  load(value:string) {this.result=value;this.readyState=2;this.onload?.();}
}
const png = () => new Blob(['sample'], {type:'image/png'});
describe('memory-only private PNG preview', () => {
  beforeEach(()=>{Reader.instances=[];vi.stubGlobal('FileReader',Reader);});
  afterEach(()=>vi.unstubAllGlobals());
  it('uses a PNG data URL accepted by the shell CSP and detaches the reader', async () => {
    const promise=readPrivatePng(png(),new AbortController().signal);
    const reader=Reader.instances[0];
    reader.load('data:image/png;base64,c2FtcGxl');
    expect(await promise).toBe('data:image/png;base64,c2FtcGxl');
    expect(reader.onload).toBeNull();expect(reader.onerror).toBeNull();
  });
  it('rejects non-PNG and oversized content before allocating a reader', async () => {
    for(const content of [new Blob(['svg'],{type:'image/svg+xml'}),new Blob([new Uint8Array(1048577)],{type:'image/png'})]) {
      await expect(readPrivatePng(content,new AbortController().signal)).rejects.toHaveProperty('code','unsafe_reference');
    }
    expect(Reader.instances).toHaveLength(0);
  });
  it('cancels the reader and ignores late pixels after identity or route changes', async () => {
    const abort=new AbortController(),promise=readPrivatePng(png(),abort.signal);
    const reader=Reader.instances[0];abort.abort();
    await expect(promise).rejects.toHaveProperty('name','AbortError');
    expect(reader.aborted).toBe(true);expect(reader.onload).toBeNull();
    reader.load('data:image/png;base64,bGF0ZQ==');
  });
  it('never allocates a reader for an already-cancelled request', async () => {
    const abort=new AbortController();abort.abort();
    await expect(readPrivatePng(png(),abort.signal)).rejects.toHaveProperty('name','AbortError');
    expect(Reader.instances).toHaveLength(0);
  });
  it('refuses an unexpected URL scheme or media type from a reader', async () => {
    const promise=readPrivatePng(png(),new AbortController().signal);
    Reader.instances[0].load('data:image/svg+xml;base64,dW5zYWZl');
    await expect(promise).rejects.toHaveProperty('code','reference_unavailable');
  });
  it('redacts reader failures rather than exposing local file error details', async () => {
    const promise=readPrivatePng(png(),new AbortController().signal);
    Reader.instances[0].onerror?.();
    await expect(promise).rejects.toMatchObject({status:503,code:'reference_unavailable',requestId:''});
  });
});
