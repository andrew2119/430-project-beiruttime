/** The existing Orders tab owns scoped review and payment state. */
export function orderReviewHref(locale:'en'|'ar',orderId:string){
 return `/${locale}/checkout/${encodeURIComponent(orderId)}`;
}
