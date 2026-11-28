import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
const state = vi.hoisted(()=>({locale:'en' as 'en'|'ar',status:'signed-out',admitted:false,session:null as null|{access_fingerprint:string}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.session,useSessionState:()=>state.status,refreshSession:vi.fn(),authenticatedRequest:vi.fn()}));
const pageRead = vi.hoisted(()=>vi.fn(()=>({data:undefined,error:null,isPending:false,isFetching:false,refetch:vi.fn()})));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:pageRead}));
vi.mock('@/shell/foundation/path',()=>({usesFoundationShell:()=>state.admitted}));
import InspectionView, { InspectionUnavailable } from '../../../../web/features/private-inspection/view';
import { deriveResult } from '../../../../web/features/private-inspection/api';
import InspectionError from '../../../../web/app/(inspections)/operations/inspections/error';
import declaration from '../../../../web/features/private-inspection/delivery-contract.json';
import { copy } from '../../../../web/features/private-inspection/copy';

describe('private inspection screen',()=>{
  it('declares its exact feature page and shared read view',()=>{
    expect(declaration).toEqual({
      route:'/operations/inspections',
      file:'web/app/(inspections)/operations/inspections/page.tsx',
      view:'web/features/private-inspection/view.tsx',
      kind:'reads',
      reason:'Assigned private-sale inspection requires current access, paid readiness and expert custody.',
      content:'form',read:'private-inspection',proof:'owed',
    });
  });
  it.each(['en','ar'] as const)('renders complete account recovery in %s',locale=>{
    state.locale=locale;state.session=null;state.status='signed-out';
    const html=renderToStaticMarkup(<InspectionView/>);
    expect(html).toContain(copy[locale].title);
    expect(html).toContain(copy[locale].signInBody);
    expect(html).toContain(`/${locale}/account`);
    expect(html).not.toContain('<main');
  });
  it.each(['en','ar'] as const)('renders unavailable recovery in %s',locale=>{
    state.locale=locale;state.session=null;state.status='unavailable';
    const html=renderToStaticMarkup(<InspectionView/>);
    expect(html).toContain(copy[locale].unavailableBody);
    expect(html).toContain(copy[locale].retry);
  });
  it.each(['en','ar'] as const)('keeps authenticated entry recoverable until shared composition admits the route in %s',locale=>{
    state.locale=locale;state.session={access_fingerprint:'scope'};state.status='authenticated';
    const html=renderToStaticMarkup(<InspectionView/>);
    expect(html).toContain(copy[locale].routeUnavailable);
    expect(html).toContain(`/${locale}/account`);
    expect(html).not.toContain('<main');
  });
  it.each(['en','ar'] as const)('mounts record lookup after shared admission in %s',locale=>{
    state.locale=locale;state.session={access_fingerprint:'scope'};state.status='authenticated';
    state.admitted=true;
    pageRead.mockClear();
    try {
      const html=renderToStaticMarkup(<InspectionView/>);
      expect(html).toContain(copy[locale].subject);
      expect(html).toContain(copy[locale].open);
      expect(html).toContain(copy[locale].emptyBody);
      expect(html).not.toContain(copy[locale].routeUnavailable);
      expect(html).not.toContain('<main');
      expect(pageRead).toHaveBeenCalledWith(null);
    } finally {state.admitted=false;}
  });
  it('renders published recovery without a shared read scope',()=>{
    state.locale='ar';state.session={access_fingerprint:'scope'};state.status='authenticated';
    const html=renderToStaticMarkup(<InspectionUnavailable/>);
    expect(html).toContain(copy.ar.routeUnavailable);
    expect(html).toContain(copy.ar.account);
    expect(html).not.toContain('localStorage');
  });
  it.each(['en','ar'] as const)('renders route recovery in %s',locale=>{
    state.locale=locale;
    const html=renderToStaticMarkup(<InspectionError reset={()=>{}}/>);
    expect(html).toContain(copy[locale].routeUnavailable);
    expect(html).toContain(copy[locale].retry);
    expect(html).not.toContain('<main');
  });
  it('derives only the actual checklist outcome',()=>{
    expect(deriveResult(['passed','passed','passed','passed'])).toBe('passed');
    expect(deriveResult(['passed','inconclusive','passed','passed'])).toBe('inconclusive');
    expect(deriveResult(['failed','inconclusive','passed','passed'])).toBe('failed');
  });
  it('keeps complete dictionary keys in both languages',()=>{
    expect(Object.keys(copy.en).sort()).toEqual(Object.keys(copy.ar).sort());
    for(const value of Object.values(copy.ar))expect(value.trim()).not.toBe('');
  });
});
