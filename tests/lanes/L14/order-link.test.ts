import { expect,it } from 'vitest';
import { orderReviewHref } from '../../../web/features/offers/order-link';

it.each(['en','ar'] as const)('uses the canonical scoped order tab in %s',locale=>{
 const id='11111111-1111-4111-8111-111111111111';
 expect(orderReviewHref(locale,id)).toBe(`/${locale}/checkout/${id}`);
});
it('never treats a returned reference as an arbitrary navigation path',()=>{
 expect(orderReviewHref('en','../other?x=1')).toBe('/en/checkout/..%2Fother%3Fx%3D1');
});
