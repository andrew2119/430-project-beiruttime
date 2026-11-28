export function offerRoute(listingMode:string,commitmentMode:string){
 return (listingMode==='fixed_price'&&commitmentMode==='fixed')||(listingMode==='offer'&&commitmentMode==='seller_base');
}
