"""Explicit V1 dependency examples for browser tests, never a runtime fallback."""
import hashlib
import secrets
import time
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from bt_runtime.request_budget import RequestBudget
from pydantic import BaseModel, Field

PASSWORD='CONTRACT-ONLY-PASSWORD'
LISTING='20000000-0000-4000-8000-000000000001'
ORDER='20000000-0000-4000-8000-000000000002'
ORG='30000000-0000-4000-8000-000000000001'
OTHER_ORG='30000000-0000-4000-8000-000000000002'
PROFILES={
 'buyer@example.invalid':('10000000-0000-4000-8000-000000000001',['buyer'],[],None),
 'seller@example.invalid':('10000000-0000-4000-8000-000000000002',['buyer','private_seller'],[],None),
 'operator@example.invalid':('10000000-0000-4000-8000-000000000003',['buyer','operator'],['moderation.review','moderation.decide','moderation.assign','identity.private-seller.review','authentication.review','disputes.review','quality.review'],None),
 'reviewer@example.invalid':('10000000-0000-4000-8000-000000000004',['buyer','operator'],['moderation.review','moderation.decide'],None),
 'technical@example.invalid':('10000000-0000-4000-8000-000000000005',['buyer','dealer'],[],ORG),
 'other-business@example.invalid':('10000000-0000-4000-8000-000000000006',['buyer','dealer'],[],OTHER_ORG),
}


class Login(BaseModel):
    email:str=Field(max_length=254)
    password:str=Field(max_length=128)


def fixture_app(origin:str):
    app=FastAPI(title='L09 CONTRACT FIXTURE — not marketplace authority')
    app.add_middleware(RequestBudget,max_bytes=65536)

    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):
        return JSONResponse({'error':{'code':'validation_error','message':'Check fixture fields.','request_id':'contract-fixture','details':{}}},status_code=422,headers={'Cache-Control':'no-store'})

    sessions={}
    access={}
    refresh={}

    @app.exception_handler(HTTPException)
    async def error(request,exc):
        return JSONResponse({'error':{'code':'unauthorized' if exc.status_code==401 else 'forbidden' if exc.status_code==403 else 'not_found',
            'message':'Contract fixture request denied.','request_id':'contract-fixture','details':{}}},status_code=exc.status_code,headers={'Cache-Control':'no-store'})

    def guard_origin(request):
        if request.headers.get('Origin')!=origin:
            raise HTTPException(403)

    def principal_for(session,selected=None):
        subject,roles,permissions,organization=PROFILES[session['email']]
        if selected is not None and selected!=organization:
            raise HTTPException(403)
        return {'actor':{'subject_id':subject,'session_id':session['id'],'organization_id':selected},
            'roles':roles,'permissions':permissions,'organizations':[organization] if organization else [],
            'organization_grants':[{'organization_id':organization,'roles':['dealer'],
                'permissions':['business.records.read','business.jobs.write']}] if organization else []}

    def authenticated(request):
        scheme,_,token=request.headers.get('Authorization','').partition(' ')
        value=access.get(token)
        if scheme.lower()!='bearer' or value is None or value[1]<=time.time():
            raise HTTPException(401)
        session=sessions.get(value[0])
        if session is None or session['expires']<=time.time():
            raise HTTPException(401)
        return session

    def issue(session):
        token=secrets.token_urlsafe(32)
        access[token]=(session['id'],time.time()+300)
        previous=session.get('refresh')
        if previous:
            refresh.pop(previous,None)
        handle=secrets.token_urlsafe(40)
        session['refresh']=handle
        refresh[handle]=session['id']
        subject=PROFILES[session['email']][0]
        result={'access_token':token,'token_type':'Bearer','expires_in':300,
            'account':{'id':subject,'email':session['email'],'display_name':'SAMPLE CONTRACT PROFILE'},
            'principal':principal_for(session),'access_fingerprint':hashlib.sha256((subject+session['id']).encode()).hexdigest()}
        response=JSONResponse(result,headers={'Cache-Control':'no-store'})
        response.set_cookie('bt_refresh',handle,httponly=True,samesite='strict',path='/')
        return response

    @app.get('/health/live')
    async def health():
        return {'status':'ok','contract_fixture':True}

    @app.post('/v1/accounts/login')
    async def login(body:Login,request:Request):
        guard_origin(request)
        if body.email not in PROFILES or body.password!=PASSWORD:
            raise HTTPException(401)
        session={'id':str(uuid4()),'email':body.email,'expires':time.time()+1800}
        sessions[session['id']]=session
        return issue(session)

    @app.post('/v1/accounts/refresh')
    async def restore(request:Request):
        guard_origin(request)
        sid=refresh.get(request.cookies.get('bt_refresh',''))
        session=sessions.get(sid)
        if session is None or session['expires']<=time.time():
            raise HTTPException(401)
        return issue(session)

    @app.post('/v1/accounts/logout')
    async def logout(request:Request):
        guard_origin(request)
        handle=request.cookies.get('bt_refresh','')
        sid=refresh.pop(handle,None)
        if sid:
            sessions.pop(sid,None)
        response=JSONResponse({'signed_out':True},headers={'Cache-Control':'no-store'})
        response.delete_cookie('bt_refresh',path='/')
        return response

    @app.get('/internal/v1/principal')
    async def principal(request:Request,organization_id:UUID|None=None):
        return principal_for(authenticated(request),str(organization_id) if organization_id else None)

    @app.get('/v1/listings/{listing_id}/report-subject')
    async def listing_subject(listing_id:UUID,request:Request):
        authenticated(request)
        if str(listing_id)!=LISTING:
            raise HTTPException(404)
        return {'id':LISTING,'seller_id':PROFILES['seller@example.invalid'][0]}

    @app.get('/v1/accounts/{subject_id}/report-subject')
    async def user_subject(subject_id:UUID,request:Request):
        authenticated(request)
        if str(subject_id) not in [profile[0] for profile in PROFILES.values()]:
            raise HTTPException(404)
        return {'subject_id':str(subject_id)}

    @app.get('/v1/private-reviews')
    async def private_reviews(request:Request):
        p=principal_for(authenticated(request))
        if 'identity.private-seller.review' not in p['permissions']:
            raise HTTPException(403)
        # Only an empty upstream queue: no decided verification result is invented.
        return {'items':[]}

    @app.get('/v1/businesses/{organization_id}')
    async def official_business(organization_id:UUID):
        if str(organization_id) not in (ORG,OTHER_ORG):
            raise HTTPException(404)
        return {'id':str(organization_id),'public_name':'SAMPLE CONTRACT DEALER','kind':'dealer',
            'capabilities':['servicing'],'state':'active','revision':1,'sample':True,
            'platform_onboarded':True,'authenticated_business':True,'independent_watch_authentication_required':False}

    @app.get('/v1/directory/providers/{organization_id}')
    async def provider(organization_id:UUID):
        if str(organization_id) not in (ORG,OTHER_ORG):
            raise HTTPException(404)
        return {'organization_id':str(organization_id),'official':True,'active':True,'kind':'dealer'}

    @app.get('/v1/custody/receipts/{receipt_id}')
    async def no_receipt(receipt_id:UUID,request:Request):
        authenticated(request)
        # This proof never fabricates physical custody; only awaiting-intake UI is exercised.
        raise HTTPException(404)

    return app
