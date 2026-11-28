import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LocaleContext } from '@/shell/locale-context';
import Returns from './returns';

describe('private returns first frame',()=>{
  for(const locale of ['en','ar'] as const){
    it(`shows honest unavailable recovery in ${locale}`,()=>{
      const html=renderToStaticMarkup(<LocaleContext.Provider value={locale}><Returns/></LocaleContext.Provider>);
      expect(html).toContain(locale==='ar'?'الإرجاع غير متاح':'Returns unavailable');
      expect(html).toContain('disabled');
      expect(html).not.toContain('localStorage');
      expect(html.match(/<main/g)).toBeNull();
    });
  }
});
