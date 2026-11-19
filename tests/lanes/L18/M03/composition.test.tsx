import { expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/features/identity/session',()=>({useSession:()=>({access_fingerprint:'current'}),signInHref:()=>'/account',authenticatedRequest:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({isPending:true})}));
import QuestionsRoute from '../../../../web/app/(questions)/questions/page';
import { Questions } from '../../../../web/features/listing-questions/view';
it('mounts the route and read adapter without an internal shell or extra provider',()=>{
 const html=renderToStaticMarkup(<QuestionsRoute/>);
 expect(html).toContain('Open questions');
 expect(html).not.toContain('temporarily unavailable');
 expect(html).not.toContain('<main');
 const opened=renderToStaticMarkup(<Questions listing="listing" signedIn onPending={()=>{}}/>);
 expect(opened).toContain('Loading questions');
});

it('declares the public page and uses the shared mounted read',()=>{
 const declaration=JSON.parse(readFileSync('web/features/listing-questions/delivery-contract.json','utf8'));
 expect(Object.keys(declaration).sort()).toEqual(['route','file','view','kind','reason','content','read','proof'].sort());
 expect(declaration).toMatchObject({route:'/questions',file:'web/app/(questions)/questions/page.tsx',view:'web/features/listing-questions/view.tsx',kind:'reads',read:'listing-questions.v1',proof:'owed'});
 const source=readFileSync(declaration.view,'utf8');
 expect(source).toContain("from '@/lib/page-speed/read'");
 expect(source).toContain('usePageRead(');
 expect(source).toContain('<PageFrame>');
 expect(source).toContain('<PageHeader ');
});
