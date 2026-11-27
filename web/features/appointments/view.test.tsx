import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import { LocaleContext } from '@/shell/locale-context';
import Appointments from './view';
import en from './en.json';
import ar from './ar.json';

const access = vi.hoisted(()=>({fingerprint:'current',roles:['buyer']}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>access}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:undefined,isFetching:false,isError:false,refetch:vi.fn()})}));
vi.mock('./api',()=>({visitRead:vi.fn(),sendVisit:vi.fn(),findOperation:vi.fn()}));
const binding = {actor_id:'buyer',subject_id:'buyer',watch_id:'watch',organization_id:'business',
  source_revision:1,policy_revision:1,assignment_revision:1,quote_id:null,quote_revision:null};

it.each(['en','ar'] as const)('renders canonical labelled controls and honest empty state in %s',locale=>{
  const t = locale === 'ar' ? ar : en;
  const html = renderToStaticMarkup(<LocaleContext value={locale}><Appointments binding={binding} businessStaff={false}/></LocaleContext>);
  expect(html).toContain(t.title);expect(html).toContain(t.notice);expect(html).toContain(t.empty);
  expect(html.match(/<h1/g)).toHaveLength(1);expect(html).not.toContain('<main');
  expect(html).toContain('bt-page-header');expect(html).toContain('bt-input');
  expect(html).toContain('type="date"');expect(html).toContain('aria-haspopup=');
  expect(html).toMatch(/<button[^>]*type="submit"/);
  expect(html).toContain('min="15"');expect(html).toContain('max="120"');
  expect(html).not.toContain(t.confirm);
});
it('renders denied without private form inputs',()=>{
  access.fingerprint = '';
  const html = renderToStaticMarkup(<Appointments binding={binding} businessStaff={false}/>);
  expect(html).toContain(en.denied);expect(html).not.toContain('<input');
  access.fingerprint = 'current';
});
