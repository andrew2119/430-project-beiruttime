export type Kind = 'color' | 'material' | 'dial' | 'sophistication';
export type Localized = { en: string; ar: string };
export type Component = 'case' | 'bezel' | 'dial' | 'hands' | 'markers' | 'strap' | 'bracelet' | 'package';
export type ColorDetails = { color: Localized; finish: Localized; coating: Localized | null; swatch: string };
export type MaterialDetails = { material: Localized; grade: string; construction: 'solid' | 'plating' | 'coating'; substrate: Localized | null; thickness_micrometers: number | null };
export type DialDetails = { dial: Localized; hands: Localized; markers: Localized; provenance: 'original' | 'aftermarket'; source_reference: string };
export type SophisticationDetails = { interventions: Localized[]; exclusions: Localized[]; required_tests: Localized[]; price_reference: string; price_minor: number; currency: 'USD' | 'LBP'; conversion: 'none' };
export type Option = { id: string; revision: number; component: Component; label: Localized; base_models: string[]; calibers: string[]; available: boolean } & (
  {kind: 'color'; details: ColorDetails} | {kind: 'material'; details: MaterialDetails} |
  {kind: 'dial'; details: DialDetails} | {kind: 'sophistication'; details: SophisticationDetails});
export type Brand = { organization_id: string; name: Localized; kind: string; status: string; offerings: string[]; sample: boolean };
export type Catalog = { brand: Brand; items: Option[] };
export type Configuration = { id: string; brand_id: string; base_model: string; caliber: string; revision: number; state: 'saved_not_submitted'; feasibility: 'not_assessed'; reference_ids: string[]; updated_at: string; selections: { kind: Kind; component: Component; option_id: string; option_revision: number; reference_ids: string[]; definition: Omit<Option, 'kind' | 'id' | 'revision'>; current: boolean }[] };
export type SelectionWrite = { brand_id: string; base_model: string; caliber: string; option_id: string; option_revision: number; expected_revision: number; component: Component; reference_ids: string[] };
