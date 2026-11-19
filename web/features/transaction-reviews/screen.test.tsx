import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
const language=vi.hoisted(()=>({value:'en'}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>language.value}));
import { ReviewForm as Screen } from './screen';
vi.mock('@/features/identity/session',()=>({useSession:()=>null,refreshSession:async()=>null}));
import { PublicReviews } from './public';
describe('transaction review states',()=>{
  it.each(['en','ar'])('renders unavailable without completion claims in %s',locale=>{
    language.value=locale;
    const html=renderToStaticMarkup(<Screen/>);
    expect(html).toContain('role="alert"');
    expect(html).toContain('review-subject');
    expect(html).toContain(locale==='ar'?'غير متاحة':'unavailable');
  });
  it('uses server totals and real pagination with mixed text',()=>{
    language.value='en';
    const html=renderToStaticMarkup(<PublicReviews data={{items:[{review_ref:'public-review-1',rating:1,text:'طويل mixed 🕰️',reply:null}],total:1000,average:1,distribution:[1000,0,0,0,0],page:2,next_page:3}} onPage={()=>{}} onReport={()=>{}}/>);
    expect(html).toContain('1,000');expect(html).toContain('طويل mixed 🕰️');expect(html).toContain('Next');
  });
});
