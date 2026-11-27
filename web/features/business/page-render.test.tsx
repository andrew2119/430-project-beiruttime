import { PageReadProvider } from '@/lib/page-speed/provider';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe,expect,it,vi } from 'vitest';
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:null})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null}));
vi.mock('next/navigation',()=>({usePathname:()=>'/business'}));
import en from './en.json';
import BusinessDirectory from './directory';
import ContactDetails from './contacts';
import MyReviewHistory from './review-history';
import VerificationDesk from './verification';
import Memberships from './membership';

describe('business pages before retained-read root adoption',()=>{
  it.each([[BusinessDirectory,en.title],[ContactDetails,en.contacts],[MyReviewHistory,en.myReviewHistory],[VerificationDesk,en.reviewTitle],[Memberships,en.membership]] as const)('renders the actual page in the shared read scope: %s',(Page,title)=>{
    const html=renderToStaticMarkup(<PageReadProvider><Page/></PageReadProvider>);
    const headings = [...html.matchAll(/<(h[1-6])\b[^>]*>([\s\S]*?)<\/\1>/g)]
      .map(match => match[2].replace(/<[^>]*>/g, ''));
    expect(headings).toContain(title);

    expect(html).not.toContain('<main');
  });
});
