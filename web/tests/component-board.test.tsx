import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { ComponentBoard } from '../internal/components/client';
import { DATA_MODES, persistBoard } from '../internal/components/model';
import { COPY } from '../internal/components/copy';
import { ThemeProvider } from '../shell/theme-provider';
import { generateMetadata } from '../app/internal/components/page';
import { Select } from '@beirut-time/ui/foundation';
import { selectRuntime } from '../../packages/ui/src/foundation/select-runtime';
import { IDENTIFIERS, NAMES, TEXT } from './fixtures/worst-case';
vi.mock('@/shell/locale',()=>({getLocale:async()=>'en'}));
const families = ['button','link','label','input','textarea','checkbox','radio','switch','select','segmented','dialog','sheet-bottom','sheet-end','sheet-responsive','sheet-phone','popover','menu','toast','skeleton','avatar','image','state','scroll','fold','list','numbers','theme','navigation','card','badge'];
function section(html:string,id:string) {const start = html.indexOf(`data-component="${id}"`);expect(start,id).toBeGreaterThanOrEqual(0);const end = html.indexOf('data-component=',start+1);return html.slice(start,end < 0 ? undefined : end);} 
afterEach(()=>vi.unstubAllGlobals());
describe('real unlisted component drawing board',()=>{
  it('composes every catalogue family in either language from canonical public components',()=>{
    for (const locale of ['en','ar'] as const) {
      const html = renderToStaticMarkup(<ThemeProvider initialTheme="light"><ComponentBoard initialMode="worst" initialLocale={locale}/></ThemeProvider>);
      for (const id of families) section(html,id);
      expect(section(html,'button')).toContain('aria-busy="true"');expect(section(html,'button')).toContain('data-success=""');expect(section(html,'button')).toContain('disabled=""');
      expect(section(html,'input')).toContain('required=""');expect(section(html,'input')).toContain('readOnly=""');expect(section(html,'input')).toContain('aria-invalid="true"');
      const label = /for="([^"]+)"/.exec(section(html,'label'));expect(label).not.toBeNull();expect(section(html,'label')).toContain(`<output id="${label![1]}"`);
      expect(section(html,'select')).toContain('archived-watch-code');expect(section(html,'select')).toContain('data-review-example="select-delivery"');
      expect(section(html,'image')).toContain('data-review-example="image-lifecycle"');expect(section(html,'image')).toContain('/demo/watches/review-panorama.svg');expect(section(html,'image')).toContain('/demo/watches/review-portrait.svg');
      expect(section(html,'state')).toContain('data-kind="error" role="alert"');expect(section(html,'state')).toContain('data-kind="loading" role="status"');
      expect(section(html,'scroll')).toContain('data-axis="horizontal"');for (const tone of ['neutral','success','warning','error']) expect(section(html,'badge')).toContain(`data-tone="${tone}"`);
      expect(html).not.toContain('data-states=');
      expect((html.match(/<h1\b/g) ?? []).length).toBe(1);expect(html).toContain(locale === 'ar' ? 'dir="rtl" lang="ar"' : 'dir="ltr" lang="en"');expect(html).toContain(COPY[locale].demo);expect(html).toContain('role="combobox"');expect(html).toContain('role="radiogroup"');expect(html).toContain('role="alert"');expect(html).toContain('role="status"');expect(html).toContain('bt-theme-switch');expect(html).toContain(NAMES.arabic);expect(html).toContain(NAMES.emojiOnly);expect(html).toContain(IDENTIFIERS.reference);expect(html).toContain('&lt;b&gt;Original dial&lt;/b&gt;');
      expect(html).not.toContain('title="'+TEXT.titleAtLimit+'"');
    }
  });
  it('changes actual user-sized props in every data-bearing family, not a catalogue attribute',()=>{
    const render = (mode:'demo'|'worst')=>renderToStaticMarkup(<ThemeProvider initialTheme="light"><ComponentBoard initialMode={mode} initialLocale="en"/></ThemeProvider>);
    const usual = render('demo'), worst = render('worst');
    for (const id of ['button','link','label','input','textarea','checkbox','radio','switch','select','segmented','dialog','sheet-bottom','sheet-end','sheet-responsive','sheet-phone','popover','menu','toast','image','fold','theme']) {
      expect(section(worst,id),id).toContain(TEXT.expandedLabel);expect(section(usual,id),id).not.toContain(TEXT.expandedLabel);
    }
    expect(section(worst,'avatar')).toContain(NAMES.sellerAtLimit);expect(section(usual,'avatar')).not.toContain(NAMES.sellerAtLimit);
    for (const id of ['card','scroll','list']) {expect(section(worst,id),id).toContain(TEXT.titleAtLimit);expect(section(usual,id),id).not.toContain(TEXT.titleAtLimit);}
    expect(section(worst,'numbers')).toContain('104,233,918');expect(section(usual,'numbers')).not.toContain('104,233,918');
    expect(section(worst,'state')).toContain(TEXT.titleAtLimit);expect(section(usual,'state')).not.toContain(TEXT.titleAtLimit);
    // Skeleton/glyphs have no arbitrary data API; badge tones are deliberately bounded state words.
    expect(section(worst,'skeleton')).toContain('bt-row-skeleton');expect(section(worst,'navigation')).toContain('bt-nav-glyph');
  });
  it('uses real extreme-aspect media sources inside the shared reserved frame, not invented image state flags',()=>{
    const panorama = readFileSync(new URL('../public/demo/watches/review-panorama.svg',import.meta.url),'utf8'), portrait = readFileSync(new URL('../public/demo/watches/review-portrait.svg',import.meta.url),'utf8');
    expect(panorama).toContain('width="4000" height="200"');expect(portrait).toContain('width="200" height="4000"');
    const html = renderToStaticMarkup(<ThemeProvider initialTheme="light"><ComponentBoard initialMode="worst" initialLocale="ar"/></ThemeProvider>);expect(section(html,'image')).toContain('aspect-ratio:480 / 360');expect(section(html,'image')).toContain('data-image-state="loading"');
  });
  it('consumes every stress mode as real props and bounds a thousand records to a complete paginated preview',()=>{
    for (const mode of DATA_MODES) {
      const html = renderToStaticMarkup(<ThemeProvider initialTheme="dark"><ComponentBoard initialMode={mode} initialLocale="en"/></ThemeProvider>);
      expect(html).toContain(COPY.en.modes[mode]);
      const data = html.slice(html.indexOf('id="data-preview"'));
      expect((data.match(/class="bt-card bt-board-watch"/g) ?? []).length).toBe(mode === 'empty' ? 0 : mode === 'one' ? 1 : mode === 'demo' ? 3 : 12);
      if (mode === 'thousand') {expect(data).toContain('1,000 watches');expect(data).toContain('84');}
      if (mode === 'empty') expect(data).toContain(COPY.en.emptyTitle);
    }
  });
  it('has explicit translated branded metadata and is never inserted into product navigation',async()=>{
    expect(await generateMetadata({searchParams:Promise.resolve({locale:'ar'})})).toEqual({title:{absolute:'مكوّنات الواجهة · بيروت تايم'},robots:{index:false,follow:false}});
    expect(await generateMetadata({searchParams:Promise.resolve({locale:'en'})})).toEqual({title:{absolute:'Interface components · Beirut Time'},robots:{index:false,follow:false}});
    const navigation = readFileSync(new URL('../registry.generated.ts',import.meta.url),'utf8');expect(navigation).not.toContain('/internal/components');
  });
  it('swaps URL-backed data and preview language instantly without a route request or losing other URL parts',()=>{
    const replaceState = vi.fn(), document = {title:''};vi.stubGlobal('window',{location:{href:'https://example.test/en/internal/components?keep=1#data-preview'},history:{replaceState}});vi.stubGlobal('document',document);
    persistBoard('thousand','ar');expect(replaceState).toHaveBeenCalledOnce();const target = replaceState.mock.calls[0][2] as URL;expect(target.searchParams.get('keep')).toBe('1');expect(target.searchParams.get('data')).toBe('thousand');expect(target.searchParams.get('locale')).toBe('ar');expect(target.hash).toBe('#data-preview');expect(document.title).toBe('مكوّنات الواجهة · بيروت تايم');
  });
});
describe('select cold frame is already the final named value box',()=>{
  it('preserves current/unknown values and error semantics without downloading popup code',()=>{
    for (const value of ['one','missing',null]) {
      const html = renderToStaticMarkup(<Select id="watch" name="watch" label="Watch" value={value} onValueChange={()=>{}} options={[{value:'one',label:NAMES.long}]} messages={COPY.en.select} error="Invalid" required/>);
      expect(html).toContain('id="watch"');expect(html).toContain('role="combobox"');expect(html).toContain('aria-invalid="true"');expect(html).toContain('aria-required="true"');expect(html).toContain(value === 'one' ? NAMES.long : value ?? COPY.en.select.placeholder);expect(html).toContain('aria-describedby="watch-error"');expect(html).not.toContain('role="listbox"');
    }
    expect(selectRuntime().status).toBe('idle');
  });
});
