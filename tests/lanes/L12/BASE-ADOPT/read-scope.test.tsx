import type { ReactNode } from '../../../../web/node_modules/@types/react';
import { expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ShellBoundary } from '../../../../web/shell/shell-boundary';
import { ThemeProvider } from '../../../../web/shell/theme-provider';
import { usePageRead } from '../../../../web/lib/page-speed/read';
import { definePageRead } from '../../../../web/lib/page-speed/definition';
import { usePageReadScope } from '../../../../web/lib/page-speed/provider';
import { featurePageContracts, validatePageTable } from '../../../../web/scripts/check-page-contract.mjs';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

vi.mock('next/navigation',()=>({usePathname:()=>'/en/care/reduction',useRouter:()=>({prefetch:vi.fn()})}));
vi.mock('next/link',()=>({default:({href,children}:{href:string;children:ReactNode})=><a href={href}>{children}</a>,useLinkStatus:()=>({pending:false})}));
vi.mock('next/dynamic',()=>({default:()=>()=>null}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:null,roles:['public']})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,useSessionState:()=> 'restoring'}));
vi.mock('@/shell/install-prompt-provider',()=>({useInstallPrompt:()=>({canInstall:false,isStandalone:false,isIOS:false})}));
const read = definePageRead({key:()=>['reduction-test'],ask:async()=>({state:'unavailable'}),warm:'safe'});
function FeatureView() {
  const answer=usePageRead(read()), scope=usePageReadScope();
  return <p data-scope={scope.key}>{answer.isPending ? 'Loading care' : 'Care'}</p>;
}
it('a declared product read mounts in the existing single shell scope without registration edits',()=>{
  const root=mkdtempSync(join(tmpdir(),'feature-scope-test-'));
  try {
    mkdirSync(join(root,'web/features/reduction'),{recursive:true});
    writeFileSync(join(root,'web/features/reduction/delivery-contract.json'),JSON.stringify({route:'/care/reduction',file:'web/app/(reduction)/care/reduction/page.tsx',view:'web/features/reduction/view.tsx',kind:'reads',reason:'Care read.',content:'[data-page-answer]',read:'reduction',proof:'owed'}));
    const {entries,owners}=featurePageContracts(root);
    expect(validatePageTable(entries,owners)).toEqual([]);
    const html=renderToStaticMarkup(<ThemeProvider initialTheme="light"><ShellBoundary serverPath={entries[0].route} locale="en" entries={[]}><FeatureView/></ShellBoundary></ThemeProvider>);
    expect(html.match(/<main\b/g)).toHaveLength(1);
    expect(html).toContain('data-scope="public"');
    expect(html).toContain('Loading care');
  } finally {rmSync(root,{recursive:true,force:true});}
});
