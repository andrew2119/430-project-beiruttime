"""Opt-in sample actor/case through real operations; never seed a review or business grant."""
import hashlib
import json
import os
from urllib.parse import urlsplit
import httpx


async def seed(settings):
    if settings.service_name != 'identity':
        raise RuntimeError('The sample fixture belongs to Identity')
    password = os.environ.get('BT_DEMO_BUYER_PASSWORD','')
    email = os.environ.get('BT_DEMO_BUYER_EMAIL','demo-buyer@example.test').strip().lower()
    if not 12 <= len(password) <= 128 or not email.endswith('.test'):
        raise RuntimeError('Supply a synthetic .test recipient and BT_DEMO_BUYER_PASSWORD of 12–128 characters')
    base = os.environ.get('BT_IDENTITY_FIXTURE_API_URL','http://127.0.0.1:8000').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in {'http','https'} or parsed.hostname not in {'localhost','127.0.0.1','::1','identity'} or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError('The sample fixture must target a local Identity origin')
    key = hashlib.sha256(email.encode()).hexdigest()[:32]
    headers = {'Origin':os.environ.get('BT_WEB_ORIGIN','http://localhost:3000')}
    async with httpx.AsyncClient(base_url=base,timeout=4,limits=httpx.Limits(max_connections=1,max_keepalive_connections=1),headers=headers) as client:
        registered = await client.post('/v1/accounts/register',headers={'Idempotency-Key':'sample-register-v1-'+key},
            json={'email':email,'password':password,'display_name':'DEMO Buyer'})
        if registered.status_code not in {201,409}:
            raise RuntimeError('Sample registration was not acknowledged')
        if registered.status_code == 201:
            await client.post('/v1/accounts/logout')
        signed = await client.post('/v1/accounts/login',json={'email':email,'password':password})
        if signed.status_code != 200:
            raise RuntimeError('Sample sign-in was not acknowledged')
        session = signed.json()
        authorization = {'Authorization':'Bearer '+session['access_token']}
        result = None
        try:
            current = await client.get('/v1/private-seller/applications/me',headers=authorization)
            if current.status_code != 200:
                raise RuntimeError('Sample private case could not be read')
            if current.json()['application'] is None:
                submitted = await client.post('/v1/private-seller/applications',headers={**authorization,'Idempotency-Key':'sample-private-v1-'+key},json={
                    'identity_name':'DEMO synthetic person','contact':email,'payout_reference':'DEMO-SAMPLE-RECIPIENT',
                    'identity_evidence':'DEMO: synthetic identity, not a real document',
                    'possession_evidence':'DEMO: synthetic possession, not a physical inspection','expected_revision':0})
                if submitted.status_code != 200:
                    raise RuntimeError('Sample private submission was not acknowledged')
            canonical = await client.get('/v1/private-seller/applications/me',headers=authorization)
            if canonical.status_code != 200 or not canonical.json()['application']:
                raise RuntimeError('Sample private case could not be reconciled')
            case = canonical.json()['application']
            if case['subject_id'] != session['account']['id']:
                raise RuntimeError('Sample private case ownership mismatch')
            result = {'sample':True,'subject_id':case['subject_id'],'application_id':case['id'],'application_status':case['status']}
        finally:
            try:
                cleanup = await client.post('/v1/accounts/logout')
                if result is not None:
                    result['session_cleanup_confirmed'] = cleanup.status_code == 200
            except httpx.HTTPError:
                if result is not None:
                    result['session_cleanup_confirmed'] = False
        print(json.dumps(result))  # Only sample markers, opaque references and acknowledged state.
        return result
