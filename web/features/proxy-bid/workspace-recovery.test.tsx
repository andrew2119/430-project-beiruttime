import {expect,it,vi} from 'vitest';
import {Children,isValidElement,type ReactElement} from 'react';
import {Segmented} from '@beirut-time/ui/foundation';
import {ApiError} from '@/lib/api/client';
import {BuyerActions} from './buyer-actions';
import {BuyerReservations} from './buyer-reservations';
import BuyerWorkspace from './buyer-workspace';
import en from './en.json';

const session=vi.hoisted(()=>({state:'authenticated',signedIn:true,fingerprint:'test-buyer',roles:['buyer']}));
const state=vi.hoisted(()=>({values:[] as unknown[],index:0}));
const source=vi.hoisted(()=>({read:vi.fn()}));
vi.mock('react',async importOriginal=>({
  ...await importOriginal<typeof import('react')>(),
  useEffect:vi.fn(),
  useState:(initial:unknown)=>{
    const index=state.index++;
    if(!(index in state.values)) state.values[index]=initial;
    return [state.values[index],(value:unknown)=>{state.values[index]=value;}];
  },
}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:source.read}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en',useLocaleChange:()=>vi.fn()}));
vi.mock('./session',()=>({
  useBuyerSession:()=>session,
}));

type Element=ReactElement<{children?:React.ReactNode;onClick?:()=>void;body?:React.ReactNode;items?:unknown[]}>;
function elements(value:React.ReactNode):Element[] {
  if(!isValidElement(value)) return [];
  const node=value as Element;
  return [node,...Children.toArray(node.props.children).flatMap(elements)];
}

it('restarts a stale cursor after denial without showing retained private activity',()=>{
  const page={schema_version:2,state:'available',total:2,next_cursor:'test-next-page',items:[{auction_id:'test-private-auction'}]};
  const refetch=vi.fn();
  function draw(error?:ApiError) {
    state.index=0;
    source.read.mockReturnValue({data:page,error,isError:Boolean(error),isSuccess:!error,isFetching:false,refetch});
    const boundary=BuyerWorkspace();
    const tree=(boundary.type as (props:unknown)=>Element)(boundary.props);
    return elements(tree);
  }
  const action=(tree:Element[],label:string)=>tree.find(node=>node.props.children===label)?.props.onClick;
  const showsRows=(tree:Element[])=>tree.some(node=>Object.values(node.props).some(value=>Object.is(value,page.items)));

  const initial=draw();
  expect(showsRows(initial)).toBe(true);
  action(initial,en.nextPage)!();
  expect(source.read.mock.lastCall?.[0].key.at(-1)).toBeNull();
  const denied=draw(new ApiError(403,'denied',''));
  expect(source.read.mock.lastCall?.[0].key.at(-1)).toBe('test-next-page');
  expect(action(denied,en.nextPage)).toBeUndefined();
  expect(showsRows(denied)).toBe(false);

  draw(new ApiError(409,'stale_cursor',''));
  const stale=draw(new ApiError(409,'stale_cursor',''));
  expect(stale.some(node=>node.type===BuyerActions)).toBe(true);
  expect(showsRows(stale)).toBe(false);
  expect(action(stale,en.firstPage)).toBeTypeOf('function');
  action(stale,en.firstPage)!();
  const restarting=draw();
  expect(source.read.mock.lastCall?.[0].key.at(-1)).toBeNull();
  expect(showsRows(restarting)).toBe(false);
  expect(draw().some(node=>node.type===BuyerActions)).toBe(true);
});

vi.mock('@/shell/foundation/path',async importOriginal=>({
  ...await importOriginal<typeof import('@/shell/foundation/path')>(),usesFoundationShell:()=>true,
}));


it('hides previously loaded private activity when current identity cannot be verified',()=>{
  state.values=[];
  const items=[{auction_id:'test-private-auction'}];
  const page={schema_version:2,state:'available',total:987654,next_cursor:null,items};
  const refetch=vi.fn();
  function draw(error?:ApiError,isFetching=false) {
    state.index=0;
    source.read.mockReturnValue({data:page,error,isError:Boolean(error),isSuccess:!error,isFetching,refetch});
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  const showsRows=(tree:Element[])=>tree.some(node=>Object.values(node.props).some(value=>Object.is(value,items)));
  expect(showsRows(draw())).toBe(true);

  const error=new ApiError(503,'unavailable','');
  for(const fetching of [false,true]) {
    const tree=draw(error,fetching);
    expect(showsRows(tree)).toBe(false);
    expect(tree.some(node=>Object.values(node.props).includes('987,654'))).toBe(false);
    expect(tree.some(node=>node.type===BuyerActions||node.type===BuyerReservations)).toBe(false);
    expect(tree.some(node=>Object.values(node.props).includes(en.unavailable))).toBe(true);
    const selector=tree.find(node=>node.type===Segmented)!;
    expect(selector.props).toMatchObject({disabled:true});
    (selector.props as {onValueChange?:(view:string)=>void}).onValueChange?.('outbid');
    expect(source.read.mock.lastCall?.[0].key.at(-2)).toBe('leading');
  }
  const checking=draw(undefined,true);
  expect(showsRows(checking)).toBe(false);
  expect(checking.find(node=>node.type===Segmented)?.props).toMatchObject({disabled:true});
  draw();
  expect(showsRows(draw())).toBe(true);
});


it('keeps independent buyer sections mounted through stale cursor recovery',()=>{
  state.values=[];
  function draw(error?:ApiError) {
    state.index=0;
    source.read.mockReturnValue({error,isError:Boolean(error),isPending:!error,refetch:vi.fn()});
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  const stale=draw(new ApiError(409,'stale_cursor',''));
  stale.find(node=>node.props.children===en.firstPage)!.props.onClick!();
  for(const tree of [stale,draw()]) {
    expect(tree.some(node=>node.type===BuyerActions)).toBe(true);
    expect(tree.some(node=>node.type===BuyerReservations)).toBe(true);
  }
});

it.each([401,403])('keeps reservation details hidden after denial %s and a failed retry',status=>{
  const retained=[{reservation_id:'test-private-reservation',total_minor:24000,currency:'USD'}];
  function draw(error?:ApiError,isFetching=false,items=retained) {
    source.read.mockReturnValue({data:{state:'available',items},error,isError:Boolean(error),isFetching,refetch:vi.fn()});
    return elements(BuyerReservations({fingerprint:'test-buyer'}));
  }
  const shows=(tree:Element[],items:typeof retained)=>tree.some(node=>Object.values(node.props).some(value=>
    Array.isArray(value)&&value.includes(items[0])));
  expect(shows(draw(),retained)).toBe(true);
  const denied=new ApiError(status,'denied','');
  const unavailable=new ApiError(503,'unavailable','');
  for(const tree of [draw(denied),draw(denied,true),draw(unavailable),draw(unavailable,true)]) {
    expect(shows(tree,retained)).toBe(false);
  }
  const current=[{reservation_id:'test-current-reservation',total_minor:25000,currency:'USD'}];
  const recovered=draw(undefined,false,current);
  expect(shows(recovered,current)).toBe(true);
  expect(shows(recovered,retained)).toBe(false);
});

it('restores independently authorized buyer actions when Auction is unavailable after denial',()=>{
  state.values=[];
  const page={schema_version:2,state:'unavailable',total:null,next_cursor:null,items:[]};
  function draw(error?:ApiError) {
    state.index=0;
    source.read.mockReturnValue({data:error?undefined:page,error,isError:Boolean(error),isSuccess:!error,isFetching:false,refetch:vi.fn()});
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  expect(draw(new ApiError(403,'denied','')).some(node=>node.type===BuyerActions)).toBe(false);
  draw();
  const restored=draw();
  expect(restored.some(node=>node.type===BuyerActions)).toBe(true);
  expect(restored.some(node=>node.type===BuyerReservations)).toBe(true);
  expect(restored.some(node=>Object.values(node.props).includes(en.unavailable))).toBe(true);
});

it('blocks cached tabs after Auction denies access until a current Auction read succeeds',()=>{
  state.values=[];
  const leading=[{auction_id:'test-leading-auction'}];
  const outbid=[{auction_id:'test-cached-outbid-auction'}];
  const available={schema_version:2,state:'available',total:1,next_cursor:null,items:leading};
  const unavailable={...available,state:'unavailable',total:null,items:[]};
  const denied=new ApiError(403,'auction_access_denied','');
  const refetch=vi.fn();
  function draw(data:unknown=available,error?:ApiError,isFetching=false) {
    state.index=0;
    source.read.mockImplementation(read=>({
      data:read?.key.at(-2)==='outbid'?{...available,items:outbid}:data,
      error,isError:Boolean(error),isSuccess:!error,isFetching,refetch,
    }));
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  const visible=(tree:Element[],items:unknown)=>tree.some(node=>Object.values(node.props).some(value=>Object.is(value,items)));
  const switchView=(tree:Element[])=> {
    const selector=tree.find(node=>node.type===Segmented)!;
    (selector.props as {onValueChange?:(view:string)=>void}).onValueChange?.('outbid');
    return selector.props;
  };
  expect(visible(draw(),leading)).toBe(true);
  for(const answer of [[available,denied,false],[available,undefined,true],[unavailable,undefined,false]] as const) {
    const tree=draw(...answer);
    expect(visible(tree,leading)).toBe(false);
    expect(visible(tree,outbid)).toBe(false);
    expect(tree.some(node=>node.type===BuyerActions)).toBe(true);
    expect(tree.some(node=>node.type===BuyerReservations)).toBe(true);
    expect(switchView(tree)).toMatchObject({disabled:true});
    expect(source.read.mock.lastCall?.[0].key.at(-2)).toBe('leading');
  }
  draw();
  const recovered=draw();
  expect(visible(recovered,leading)).toBe(true);
  expect(switchView(recovered)).toMatchObject({disabled:false});
  expect(visible(draw(),outbid)).toBe(true);
});

it('waits for a fresh scoped answer after restoring the same buyer session',()=>{
  state.values=[];
  const items=[{auction_id:'test-retained-auction'}];
  const page={schema_version:2,state:'available',total:987654,next_cursor:null,items};
  const readKeys=new Map<string,unknown>();
  const refetch=vi.fn();
  let currentAnswer:unknown;
  source.read.mockImplementation(read=>{
    const key=JSON.stringify(read?.key);
    const data=readKeys.get(key)??currentAnswer;
    if(data) readKeys.set(key,data);
    return {data,isSuccess:Boolean(data),isPending:!data,isFetching:!data,refetch};
  });
  const draw=()=>{
    state.index=0;
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  };
  const visible=(tree:Element[],value:unknown)=>tree.some(node=>Object.values(node.props).some(prop=>Object.is(prop,value)));
  currentAnswer=page;
  expect(visible(draw(),items)).toBe(true);
  const originalKey=source.read.mock.lastCall?.[0].key;
  currentAnswer=undefined;
  try {
    session.state='unavailable';
    expect(visible(draw(),items)).toBe(false);
    session.state='authenticated';
    for(const tree of [draw(),draw()]) {
      expect(visible(tree,items)).toBe(false);
      expect(visible(tree,'987,654')).toBe(false);
      expect(tree.some(node=>node.type===BuyerActions||node.type===BuyerReservations)).toBe(false);
    }
    expect(source.read.mock.lastCall?.[0].key).not.toEqual(originalKey);
    currentAnswer={...page,state:'unavailable',total:null,items:[]};
    draw();
    const restored=draw();
    expect(restored.some(node=>node.type===BuyerActions)).toBe(true);
    expect(restored.some(node=>node.type===BuyerReservations)).toBe(true);
    expect(visible(restored,items)).toBe(false);
  } finally {
    session.state='authenticated';
  }
});

it('offers a first-page restart when later activity repeats a row or ends early',()=>{
  state.values=[];
  const items=[{auction_id:'test-first-auction'}];
  const first={schema_version:2,state:'available',total:1000,next_cursor:'test-next',items};
  function draw(data:unknown) {
    state.index=0;
    source.read.mockReturnValue({data,isSuccess:true,refetch:vi.fn()});
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  draw(first).find(node=>node.props.children===en.nextPage)!.props.onClick!();
  for(const later of [
    {...first, next_cursor:'test-third'},
    {...first, next_cursor:null, items:[{auction_id:'test-second-auction'}]},
  ]) {
    const tree=draw(later);
    expect(tree.some(node=>Object.values(node.props).some(value=>Object.is(value,later.items)))).toBe(false);
    expect(tree.some(node=>node.props.children===en.firstPage)).toBe(true);
    expect(tree.some(node=>node.type===BuyerReservations)).toBe(true);
  }
});

it('confirms the restored buyer on a stale second page without restoring activity rows',()=>{
  state.values=[];
  const items=[{auction_id:'test-private-auction'}];
  const first={schema_version:2,state:'available',items,total:2,next_cursor:'test-page-two'};
  const stale=new ApiError(409,'stale_cursor','');
  function draw(data?:typeof first,error?:ApiError) {
    state.index=0;
    source.read.mockReturnValue({data,error,isSuccess:Boolean(data)&&!error,isError:Boolean(error),
      isPending:!data&&!error,isFetching:!data&&!error,refetch:vi.fn()});
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  draw(first).find(node=>node.props.children===en.nextPage)!.props.onClick!();
  try {
    session.state='unavailable';
    draw();
    session.state='authenticated';
    expect(draw().some(node=>node.type===BuyerActions)).toBe(false);
    expect(draw().some(node=>node.type===BuyerActions)).toBe(false);
    expect(source.read.mock.lastCall?.[0].key.at(-1)).toBe('test-page-two');
    draw(first,stale);
    const restored=draw(first,stale);
    expect(restored.some(node=>node.type===BuyerActions)).toBe(true);
    expect(restored.some(node=>node.type===BuyerReservations)).toBe(true);
    expect(restored.some(node=>node.props.children===en.firstPage)).toBe(true);
    expect(restored.some(node=>Object.values(node.props).some(value=>Object.is(value,items)))).toBe(false);
  } finally {
    session.state='authenticated';
  }
});

it.each(['pending','unknown'] as const)('keeps a held %s result and pagination available until access is denied',financialState=>{
  state.values=[];
  const item={
    auction_id:'test-held-auction',listing_id:'test-listing',state:'won',financial_state:financialState,
    next_action:'contact_support',order_id:financialState==='unknown'?'test-held-order':null,
  };
  const refetch=vi.fn();
  const items=[item,{auction_id:'test-other-auction',state:'won',next_action:'review_order'}];
  function draw(error?:ApiError) {
    state.index=0;
    source.read.mockReturnValue({
      data:{schema_version:2,state:'available',items,total:1000,next_cursor:'test-next-page'},
      isSuccess:!error,isError:Boolean(error),error,refetch,
    });
    const boundary=BuyerWorkspace({resultView:'won'});
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  }
  const page=draw();
  expect(page.some(node=>node.props.children===en.auctionHelpBody)).toBe(true);
  expect(page.some(node=>node.props.items===items)).toBe(true);
  page.find(node=>node.props.children===en.nextPage)!.props.onClick!();
  draw();
  expect(source.read.mock.lastCall?.[0].key.at(-1)).toBe('test-next-page');

  const denied=draw(new ApiError(403,'denied',''));
  expect(denied.some(node=>node.props.items===items)).toBe(false);
  expect(denied.some(node=>node.props.children===en.auctionHelpBody)).toBe(false);
});

it('rechecks the same buyer on a new visit before showing retained rows, totals or actions',()=>{
  state.values=[];
  const items=[{auction_id:'test-reopened-private-auction'}];
  const page={schema_version:2,state:'available',total:987654,next_cursor:null,items};
  const refetch=vi.fn();
  let previousKey:string|undefined;
  let error:ApiError|undefined;
  let isFetchedAfterMount=true;
  source.read.mockImplementation(read=>{
    const key=JSON.stringify(read?.key);
    previousKey??=key;
    const data=key===previousKey?page:undefined;
    return {data,error,isError:Boolean(error),isSuccess:Boolean(data),isPending:!data&&!error,isFetchedAfterMount,refetch};
  });
  const draw=()=>{
    state.index=0;
    const boundary=BuyerWorkspace();
    return elements((boundary.type as (props:unknown)=>Element)(boundary.props));
  };
  const visible=(tree:Element[],value:unknown)=>tree.some(node=>Object.values(node.props).some(prop=>Object.is(prop,value)));
  expect(visible(draw(),items)).toBe(true);
  state.values=[];
  isFetchedAfterMount=false;
  const verifying=draw();
  expect(JSON.stringify(source.read.mock.lastCall?.[0].key)).toBe(previousKey);
  expect(visible(verifying,en.loading)).toBe(true);
  expect(visible(verifying,items)).toBe(false);
  isFetchedAfterMount=true;
  expect(visible(draw(),items)).toBe(true);
  for(const failure of [new ApiError(403,'denied',''),new ApiError(503,'unavailable','')]) {
    state.values=[];
    error=failure;
    const reopened=draw();
    expect(visible(reopened,items)).toBe(false);
    expect(visible(reopened,'987,654')).toBe(false);
    expect(reopened.some(node=>node.type===BuyerActions||node.type===BuyerReservations)).toBe(false);
  }
});

it('follows a reservation continuation on an empty page and can restart after a source outage',()=>{
  state.values=[];
  const cursor='00000000-0000-4000-8000-000000000010';
  const first={state:'available',items:[],next_cursor:cursor};
  const last={state:'available',items:[{reservation_id:'test-last-reservation',currency:'USD'}],next_cursor:null};
  function draw(data:unknown,error?:ApiError) {
    state.index=0;
    source.read.mockReturnValue({data,error,isError:Boolean(error),isFetching:false,refetch:vi.fn()});
    return elements(BuyerReservations({fingerprint:'test-buyer'}));
  }
  const action=(tree:Element[],label:string)=>tree.find(node=>node.props.children===label)?.props.onClick;

  const initial=draw(first);
  expect(action(initial,en.nextPage)).toBeTypeOf('function');
  action(initial,en.nextPage)!();
  const later=draw(last);
  expect(source.read.mock.lastCall?.[0].key.at(-1)).toBe(cursor);
  expect(later.some(node=>node.props.items?.some(item=>(item as {reservation_id:string}).reservation_id==='test-last-reservation'))).toBe(true);
  expect(action(later,en.nextPage)).toBeUndefined();

  const unavailable=draw(last,new ApiError(503,'unavailable',''));
  expect(unavailable.some(node=>node.props.items?.length)).toBe(false);
  action(unavailable,en.firstPage)!();
  draw(first);
  expect(source.read.mock.lastCall?.[0].key).toEqual(['L16','buyer-reservations','test-buyer']);
});
