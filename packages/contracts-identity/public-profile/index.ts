export type Availability = 'ready'|'pending'|'denied'|'stale'|'unavailable';
export type SellerProfile = {
 schema_version:'public-profile.v1'; operation_id:string; subject_id:string; revision:number; state:Availability;
 identity:null|{name:string;city:string|null;kind:'private'|'dealer';member_since:string;verification:'private_seller_approved'|'dealer_business_verified';logo:string|null;banner:string|null};
 sales:{state:Availability;released_count:number|null};
 reviews:{state:Availability;distribution:number[]|null};
 listings:{state:Availability;items:{id:string;title:string}[];total:number|null;page:number;page_size:20};
};
export const publicProfileOperation = {method:'GET',path:'/v1/public-profiles/{subject_id}',version:'public-profile.v1'} as const;
