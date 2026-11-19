import type { SellerProfile } from '@contracts/contracts-identity/public-profile';
const states=new Set(['ready','pending','denied','stale','unavailable']);
const record=(value:unknown):value is Record<string,unknown>=>!!value && typeof value==='object' && !Array.isArray(value);
const count=(value:unknown)=>typeof value==='number' && Number.isSafeInteger(value) && value>=0;
const text=(value:unknown,max:number)=>typeof value==='string' && value.length>0 && value.length<=max;
const asset=(value:unknown)=>value===null || typeof value==='string' && /^\/media\/[a-zA-Z0-9/_-]{1,180}\.(png|jpg|jpeg)$/.test(value);
/** Validate the complete public response before any value reaches the page. */
export function validateProfile(value:unknown,id:string,page:number,operation?:string):SellerProfile {
 if (!record(value) || value.schema_version!=='public-profile.v1' || value.subject_id!==id || !(typeof value.operation_id==='string' && /^[a-zA-Z0-9-]{1,80}$/.test(value.operation_id)) || operation!==undefined && value.operation_id!==operation || !count(value.revision) || !states.has(String(value.state))) throw new Error('Invalid profile binding');
 const identity=value.identity;
 if (value.state==='ready') {
  if (!record(identity) || !text(identity.name,180) || !(identity.city===null || text(identity.city,120)) || !['private','dealer'].includes(String(identity.kind)) || identity.verification!==(identity.kind==='private'?'private_seller_approved':'dealer_business_verified') || !asset(identity.logo) || !asset(identity.banner) || identity.kind==='private' && (identity.logo!==null || identity.banner!==null) || typeof identity.member_since!=='string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|\+00:00)$/.test(identity.member_since) || !Number.isFinite(Date.parse(identity.member_since)) || value.revision===0) throw new Error('Invalid public identity');
 } else if (identity!==null) throw new Error('Invalid unavailable identity');
 const {sales,reviews,listings}=value;
 if (!record(sales) || !states.has(String(sales.state)) || !(sales.state==='ready'?count(sales.released_count):sales.released_count===null)) throw new Error('Invalid sales');
 if (!record(reviews) || !states.has(String(reviews.state)) || !(reviews.state==='ready'?Array.isArray(reviews.distribution) && reviews.distribution.length===5 && reviews.distribution.every(count):reviews.distribution===null)) throw new Error('Invalid reviews');
 if (!record(listings) || !states.has(String(listings.state)) || listings.page!==page || listings.page_size!==20 || !Array.isArray(listings.items) || listings.items.length>20 || !(listings.state==='ready'?count(listings.total):listings.total===null && listings.items.length===0)) throw new Error('Invalid listing page');
 if (!listings.items.every(item=>record(item) && typeof item.id==='string' && /^[a-zA-Z0-9-]{1,80}$/.test(item.id) && text(item.title,300))) throw new Error('Invalid listing');
 if (listings.state==='ready' && listings.items.length!==Math.min(20,Math.max(0,Number(listings.total)-(page-1)*20))) throw new Error('Invalid listing total');
 return value as unknown as SellerProfile;
}
