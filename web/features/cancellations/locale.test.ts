import {afterEach,describe,expect,it,vi} from 'vitest';
const mounted=vi.hoisted(()=>({effect:null as null|(()=>void|(()=>void)),refresh:vi.fn()}));
vi.mock('react',()=>({useEffect:(effect:()=>void|(()=>void))=>{mounted.effect=effect;}}));
vi.mock('next/navigation',()=>({useRouter:()=>({refresh:mounted.refresh})}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
import {changeLanguage,useCancellationLocale} from './locale';

afterEach(()=>{vi.unstubAllGlobals();vi.clearAllMocks();});
describe('root language refresh',()=>{
 function environment(){
  let href='https://example.test/en/cancellations?view=pending#reference';
  const replaceState=vi.fn((_state:unknown,_title:string,next:string)=>{href=next;});
  const addEventListener=vi.fn(),removeEventListener=vi.fn();
  const page={cookie:'',addEventListener,removeEventListener};
  vi.stubGlobal('document',page);
  vi.stubGlobal('window',{location:{get href(){return href;},origin:'https://example.test',pathname:'/en/cancellations'},history:{state:{retained:true},replaceState}});
  return {page,replaceState,addEventListener,removeEventListener};
 }
 it('updates the root URL and preference then refreshes without replacing history state',()=>{
  const {page,replaceState}=environment();
  const refresh=vi.fn();
  changeLanguage('ar',refresh);
  expect(replaceState).toHaveBeenCalledWith({retained:true},'', 'https://example.test/ar/cancellations?view=pending#reference');
  expect(page.cookie).toContain('bt-locale=ar;');
  expect(refresh).toHaveBeenCalledTimes(1);
 });
 it('routes the shell language link through the same refresh and removes its listener',()=>{
  const {addEventListener,removeEventListener}=environment();
  class Element {closest(){return this;}}
  class Anchor extends Element {href='https://example.test/ar/cancellations?view=pending';target='';download='';}
  vi.stubGlobal('Element',Element);vi.stubGlobal('HTMLAnchorElement',Anchor);
  const context=useCancellationLocale();
  expect(context.locale).toBe('en');
  const cleanup=mounted.effect!();
  const listener=addEventListener.mock.calls[0][1];
  const event={target:new Anchor(),button:0,preventDefault:vi.fn(),stopPropagation:vi.fn()};
  listener(event);
  expect(event.preventDefault).toHaveBeenCalledTimes(1);
  expect(event.stopPropagation).toHaveBeenCalledTimes(1);
  expect(mounted.refresh).toHaveBeenCalledTimes(1);
  listener({...event,ctrlKey:true});
  expect(mounted.refresh).toHaveBeenCalledTimes(1);
  if(typeof cleanup==='function')cleanup();
  expect(removeEventListener).toHaveBeenCalledWith('click',listener,true);
 });
});
