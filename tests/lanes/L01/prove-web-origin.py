"""Prove real cookie/session mutations through a locally published production web origin."""
import http.cookiejar
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor,Request,build_opener

origin=os.environ.get('BT_PROOF_WEB_ORIGIN','http://localhost:33101').rstrip('/')
parsed=urlsplit(origin)
if parsed.scheme!='http' or parsed.hostname not in {'localhost','127.0.0.1','::1'} or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
    raise SystemExit('Only a loopback HTTP proof origin is allowed')
email,password=os.environ.get('BT_PROOF_EMAIL'),os.environ.get('BT_PROOF_PASSWORD')
if not email or not password:
    raise SystemExit('Supply synthetic proof credentials through BT_PROOF_EMAIL and BT_PROOF_PASSWORD')
jar=http.cookiejar.CookieJar()
client=build_opener(HTTPCookieProcessor(jar))
base='/api/web/v1/identity/v1/accounts'


def invoke(path,body=None,token=None,supplied_origin=origin):
    headers={'Accept':'application/json'}
    if supplied_origin is not None:headers['Origin']=supplied_origin
    if token:headers['Authorization']='Bearer '+token
    data=json.dumps(body).encode() if body is not None else None
    if data is not None:headers['Content-Type']='application/json'
    request=Request(origin+path,data=data,headers=headers,method='POST' if data is not None else 'GET')
    try:
        response=client.open(request,timeout=5)
    except HTTPError as error:
        response=error
    with response:
        payload=response.read(1048577)
        assert len(payload)<=1048576,'Proof response exceeded its byte budget'
        return response.status,json.loads(payload)


for supplied in ['https://foreign.example',None]:
    status,payload=invoke(base+'/login',{'email':email,'password':password},supplied_origin=supplied)
    assert status==403 and payload.get('error',{}).get('code')=='invalid_origin'
status,session=invoke(base+'/login',{'email':email,'password':password})
assert status==200,{'status':status,'code':session.get('error',{}).get('code')}
assert 'buyer' in session['principal']['roles']
handle=next(cookie.value for cookie in jar if cookie.name=='bt_refresh')
status,account=invoke(base+'/me',token=session['access_token'])
assert status==200 and account['id']==session['account']['id']
status,case=invoke('/api/web/v1/identity/v1/private-seller/applications/me',token=session['access_token'])
assert status==200
if case['application'] is not None:
    assert case['application']['subject_id']==account['id']
status,renewed=invoke(base+'/refresh',{})
assert status==200
assert next(cookie.value for cookie in jar if cookie.name=='bt_refresh')!=handle
status,logout=invoke(base+'/logout',{})
assert status==200 and logout=={'signed_out':True}
revoked_status,_=invoke(base+'/me',token=renewed['access_token'])
assert revoked_status==401
refresh_status,_=invoke(base+'/refresh',{})
assert refresh_status==401 and not any(cookie.name=='bt_refresh' for cookie in jar)
print(json.dumps({'origin':origin,'login':200,'refresh_rotated':True,'private_case_owner_checked':True,'logout':True,
    'revoked_access':revoked_status,'refresh_after_logout':refresh_status,'foreign_or_missing_origin':403}))
