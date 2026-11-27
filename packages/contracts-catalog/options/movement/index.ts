export type { Movement, Configuration, MovementSelection } from '../../../contracts-service/directory';
export type CompatibilityRule = {case:string;dial:string;hands:string;functions:string[];state:'supported_for_review'|'incompatible'|'parts_unavailable'};
export type MovementOffering = {brand_id:string;expected_revision:number;label_en:string;label_ar:string;caliber:string;cases:string[];dials:string[];hands:string[];functions:string[];quote_minor:number;currency:'USD';active:boolean;compatibility_rules:CompatibilityRule[]};
