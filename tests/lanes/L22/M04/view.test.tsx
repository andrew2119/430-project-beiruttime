import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError } from '../../../../web/lib/api/client';
import { MessagesView } from '../../../../web/features/messages/view';
const state=vi.hoisted(()=>({locale:'en',data:undefined as unknown,error:null as unknown,pending:false}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'current-access'}),authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.data,error:state.error,isPending:state.pending,refetch:vi.fn()})}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:unknown})=>children}));
describe('private conversation list',()=>{
  it('renders both languages with a server total and bounded page',()=>{
    state.error=null;state.pending=false;
    state.data={items:Array.from({length:20},(_,i)=>({id:String(i),kind:'listing',subject_id:`ساعة watch ⌚ ${i}`})),total:1000,next_cursor:20};
    for(const locale of ['en','ar']) {state.locale=locale;const html=renderToStaticMarkup(<MessagesView/>);expect(html).toContain(locale==='ar'?'١٬٠٠٠':'1,000');expect(html).toContain('ساعة watch ⌚ 19');expect(html).not.toContain('ساعة watch ⌚ 20');expect(html).toContain(locale==='ar'?'الصفحة التالية':'Next page');}
  });
  it.each([[0,'0','٠'],[1,'1','١'],[1000,'1,000','١٬٠٠٠']])('formats the server count %s in both languages',(total,english,arabic)=>{
    state.error=null;state.pending=false;state.data={items:[],total,next_cursor:null};
    state.locale='en';expect(renderToStaticMarkup(<MessagesView/>)).toContain(`Total: ${english}`);
    state.locale='ar';expect(renderToStaticMarkup(<MessagesView/>)).toContain(`الإجمالي: ${arabic}`);
  });
  it.each([401,403,404])('hides retained private rows after a denied refresh (%s)',status=>{
    for(const locale of ['en','ar']) {
      state.locale=locale;state.pending=false;state.error=null;
      state.data={items:[{id:'private-thread',kind:'business',subject_id:'private-record',original_work_id:'private-original'}],total:1234,next_cursor:20};
      const loaded=renderToStaticMarkup(<MessagesView/>);
      expect(loaded).toContain('private-record');expect(loaded).toContain('private-original');
      state.error=new ApiError(status,'scope','');
      const denied=renderToStaticMarkup(<MessagesView/>);
      expect(denied).toContain(locale==='ar'?'الوصول مرفوض':'Access denied');
      for(const value of ['private-record','private-original','1234',locale==='ar'?'الصفحة التالية':'Next page']) expect(denied).not.toContain(value);
      state.error=null;
      expect(renderToStaticMarkup(<MessagesView/>)).toContain('private-record');
    }
  });
  it('renders honest initial loading and empty recovery',()=>{
    state.locale='en';state.data=undefined;state.pending=true;expect(renderToStaticMarkup(<MessagesView/>)).toContain('aria-busy="true"');
    state.pending=false;state.data={items:[],total:0,next_cursor:null};expect(renderToStaticMarkup(<MessagesView/>)).toContain('No messages yet');
  });
  it('renders unavailable recovery without invented rows',()=>{
    state.locale='ar';state.data=undefined;state.pending=false;state.error=new Error('unavailable');const html=renderToStaticMarkup(<MessagesView/>);expect(html).toContain('الرسائل غير متاحة');expect(html).not.toContain('ساعة watch');
  });
});
