import type {ReactNode} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {expect,it,vi} from 'vitest';
import {ApiError} from '@/lib/api/client';
import {LocaleContext} from '@/shell/locale-context';
import {BuyerSupport} from './buyer-support';
import {deliverSupport,openSupport,prepareSupport,supportRead,type SupportConversation} from './support-api';

const source=vi.hoisted(()=>({read:vi.fn(),request:vi.fn()}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:source.read}));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:ReactNode})=>children}));
vi.mock('./session',()=>({
  useBuyerSession:()=>({state:'authenticated',signedIn:true,roles:['buyer'],organizationId:null,
    subjectId:'00000000-0000-4000-8000-000000000001',fingerprint:'test-buyer'}),
  authenticatedRequest:source.request,
}));
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const conversation:SupportConversation={schema_version:1,auction_id:id(2),buyer_id:id(1),conversation_id:id(3),order_id:null,
  revision:1,hold_state:'active',assignment_state:'awaiting_operator',operator_id:null,follow_up_due_at:'2030-01-02T10:00:00Z',
  escalate_at:'2030-01-03T10:00:00Z',items:[],next_cursor:null};

it.each(['en','ar'] as const)('shows unassigned 24-hour follow-up and allows a private support message in %s',locale=>{
  const draw=()=>renderToStaticMarkup(<LocaleContext value={locale}><BuyerSupport auctionId={id(2)} listingId={id(4)}/></LocaleContext>);
  source.read.mockReturnValue({data:conversation,isFetchedAfterMount:true});
  const html=draw();
  expect(html).toContain(locale==='en'?'No support operator has been assigned yet':'لم يُعيَّن مسؤول دعم بعد');
  expect(html).toContain(locale==='en'?'within 24 hours':'خلال ٢٤ ساعة');
  expect(html).toContain('<textarea');
  source.read.mockReturnValue({data:{...conversation,assignment_state:'assigned',operator_id:id(5),order_id:id(6),
    items:[{sequence:1,author:'support',body:'Support ما زال متاحًا',sent_at:conversation.follow_up_due_at}]},isFetchedAfterMount:true});
  expect(draw()).toContain('Support ما زال متاحًا');
  source.read.mockReturnValue({isError:true,error:new ApiError(403,'denied',''),data:conversation,isFetchedAfterMount:true});
  expect(draw()).not.toContain('<textarea');
  expect(draw()).not.toContain('2030-01-02');
});

it('offers explicit opening only for a currently authorized unopened conversation',()=>{
  const draw=()=>renderToStaticMarkup(<BuyerSupport auctionId={id(2)} listingId={id(4)}/>);
  source.read.mockReturnValue({isError:true,isFetchedAfterMount:false,error:new ApiError(404,'support_not_open','')});
  expect(draw()).not.toContain('Open support conversation');
  source.read.mockReturnValue({isError:true,isFetchedAfterMount:true,error:new ApiError(404,'support_not_open','')});
  expect(draw()).toContain('Open support conversation');
  source.read.mockReturnValue({isError:true,isFetchedAfterMount:true,error:new ApiError(404,'not_found','')});
  expect(draw()).toContain('Support is temporarily unavailable');
  expect(draw()).not.toContain('Open support conversation');
  source.read.mockReturnValue({isError:true,isFetchedAfterMount:true,error:new ApiError(404,'support_history_missing','')});
  expect(draw()).toContain('There is no support conversation for this result.');
  expect(draw()).not.toContain('Open support conversation');
});

it.each(['en','ar'] as const)('reads the resolved conversation without offering to open or send in %s',async locale=>{
  const draw=()=>renderToStaticMarkup(<LocaleContext value={locale}>
    <BuyerSupport auctionId={id(2)} listingId={id(4)} historyOnly/>
  </LocaleContext>);
  const message='Original support reply · ردّ الدعم';
  const resolved={...conversation,order_id:id(6),revision:4,hold_state:'resolved' as const,
    items:[{sequence:1,author:'support' as const,body:message,sent_at:conversation.follow_up_due_at}]};
  source.request.mockReset().mockResolvedValueOnce(resolved);
  const current=await supportRead(id(2),id(1),'test-buyer',null).ask(new AbortController().signal);
  expect(source.request.mock.calls[0][0]).toBe(`/api/web/v1/communications/v1/support/auction-results/${id(2)}`);
  expect(source.request.mock.calls[0][1]).not.toHaveProperty('method','POST');
  source.read.mockReturnValue({data:current,isFetchedAfterMount:true});
  expect(draw()).toContain(locale==='en'?'Auction support history':'سجلّ دعم المزاد');
  expect(draw()).toContain(message);
  expect(draw()).not.toContain('<textarea');
  for(const code of ['support_history_missing','support_not_open','not_found']) {
    source.read.mockReturnValue({data:current,isFetchedAfterMount:true,isError:true,error:new ApiError(404,code,'')});
    const html=draw();
    const empty=locale==='en'?'There is no support conversation for this result.':'لا توجد محادثة دعم لهذه النتيجة.';
    if(code==='not_found') expect(html).not.toContain(empty);
    else expect(html).toContain(empty);
    expect(html).not.toContain(message);
    expect(html).not.toContain(locale==='en'?'Open support conversation':'افتح محادثة الدعم');
    expect(html).not.toContain('<textarea');
  }
  expect(source.request).toHaveBeenCalledTimes(1);
});

it('opens one scoped conversation and rejects a reply bound to a different buyer',async()=>{
  const signal=new AbortController().signal;
  source.request.mockReset().mockResolvedValueOnce(conversation).mockResolvedValueOnce({...conversation,buyer_id:id(9)});
  await expect(openSupport(id(2),id(1),'test-buyer',id(5),signal)).resolves.toEqual(conversation);
  expect(source.request.mock.calls[0]).toEqual([`/api/web/v1/communications/v1/support/auction-results/${id(2)}`,{
    signal,accessFingerprint:'test-buyer',cache:'no-store',method:'POST',
    headers:{'Content-Type':'application/json','Idempotency-Key':id(5)},body:'{}',
  }]);
  await expect(supportRead(id(2),id(1),'test-buyer',null).ask(signal)).rejects.toMatchObject({code:'invalid_support_response'});
});

it('refuses a conversation answer without an explicit current hold capability',async()=>{
  source.request.mockReset().mockResolvedValueOnce({...conversation,hold_state:undefined});
  await expect(supportRead(id(2),id(1),'test-buyer',null).ask(new AbortController().signal))
    .rejects.toMatchObject({status:503,code:'invalid_support_response'});
});

it('prepares the exact scoped message and retries only its bound delivery reference',async()=>{
  const signal=new AbortController().signal;
  const command={conversation_id:id(3),expected_revision:1,body:'حالة الدفع؟'};
  const receipt={schema_version:1,auction_id:id(2),buyer_id:id(1),conversation_id:id(3),operation_id:id(5),state:'accepted',revision:2};
  source.request.mockReset().mockResolvedValueOnce({...receipt,state:'prepared',revision:1})
    .mockRejectedValueOnce(new ApiError(503,'unavailable','')).mockResolvedValueOnce(receipt);
  await expect(prepareSupport(id(2),id(1),'test-buyer',id(5),command,signal)).resolves.toMatchObject({state:'prepared'});
  const deliver=()=>deliverSupport(id(2),id(1),'test-buyer',id(5),id(3),signal);
  await expect(deliver()).rejects.toMatchObject({status:503});
  await expect(deliver()).resolves.toEqual(receipt);
  expect(source.request.mock.calls[0][1].body).toBe(JSON.stringify(command));
  expect(source.request.mock.calls[1][1].body).toBe(JSON.stringify({conversation_id:id(3)}));
  expect(source.request.mock.calls[1]).toEqual(source.request.mock.calls[2]);
});
