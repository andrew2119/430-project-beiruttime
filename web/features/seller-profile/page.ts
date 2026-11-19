/** Repeated or out-of-range page criteria return to the first public page. */
export function sellerPage(value: string | string[] | undefined): number {
 if (typeof value !== 'string' || !/^[1-9]\d{0,5}$/.test(value)) return 1;
 const page=Number(value);
 return page<=100000?page:1;
}
