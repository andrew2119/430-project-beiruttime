import {beforeEach,expect,it,vi} from 'vitest';
import {BuyerLanguageControl} from './buyer-language';

const language=vi.hoisted(()=>({current:'en',change:vi.fn()}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>language.current,useLocaleChange:()=>language.change}));
beforeEach(()=>language.change.mockReset());

it.each([['en','ar'],['ar','en']])('keeps the mounted route and changes %s to %s through shared locale state',(current,next)=>{
  language.current=current;
  const control=BuyerLanguageControl();
  expect(control.props.value).toBe(current);
  control.props.onValueChange(current);
  control.props.onValueChange('invalid');
  expect(language.change).not.toHaveBeenCalled();
  control.props.onValueChange(next);
  expect(language.change).toHaveBeenCalledExactlyOnceWith(next);
});
