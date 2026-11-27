"""Publish the labelled sample through real APIs; never insert business outcomes.
Run while the own --listing-authorities proof holds the shared heavy reservation.
"""
import asyncio
import json
from pathlib import Path
from uuid import uuid4
import httpx

OUT = Path(__file__).resolve().parent / '.artifacts'
ORIGIN = 'http://127.0.0.1:3315'


async def main():
    public = json.loads((OUT/'proof-public.json').read_text())
    actor = json.loads((OUT/'actors.key').read_text())['brand']
    retained_path = OUT/'publication-commands.key'
    retained = json.loads(retained_path.read_text()) if retained_path.exists() else {}
    retained.setdefault('listing_id', public['listing_id'])
    if retained['listing_id'] != public['listing_id']:
        retained = {'listing_id':public['listing_id']}

    def save():
        retained_path.write_text(json.dumps(retained, indent=2))
        retained_path.chmod(0o600)

    async with httpx.AsyncClient(timeout=20) as client:
        login = await client.post('http://127.0.0.1:8315/v1/accounts/login',
            headers={'Origin':ORIGIN},json={'email':actor['email'],'password':actor['password']})
        login.raise_for_status()
        token = login.json()['access_token']

        async def request(service, method, path, *, body=None, data=None, revision=None, stage=None):
            header = {'Origin':ORIGIN,'Authorization':'Bearer '+token}
            if stage:
                retained.setdefault(stage+'_key',uuid4().hex)
                save()
                header['Idempotency-Key'] = retained[stage+'_key']
            if revision:
                header['If-Match'] = str(revision)
            if data is not None:
                header['Content-Type'] = 'application/octet-stream'
            port = {'catalog':8415,'pricing':8615}[service]
            response = await client.request(method,f'http://127.0.0.1:{port}'+path,
                headers=header,json=body,content=data)
            if response.status_code >= 400:
                raise RuntimeError(f'{service} {method} {path}: {response.status_code} {response.text}')
            return response.json()

        scope = '?organization_id='+public['brand_id']
        path = '/v1/seller/listings/'+public['listing_id']
        row = await request('catalog','GET',path+scope)
        if row['status'] == 'draft' and not row['photo_ids']:
            result = await request('catalog','POST',path+'/media'+scope+'&kind=public_photo&public_safe=true',
                data=(Path(__file__).resolve().parents[3]/'web/public/demo/watches/seiko-5.jpg').read_bytes(),
                revision=row['revision'],stage='photo')
            row = result['listing']
        if row['status'] != 'published':
            if 'quote' not in retained:
                retained['quote'] = await request('pricing','POST','/v1/quotes',body={
                    'subject_id':row['id'],'subject_revision':row['revision'],'purpose':'purchase',
                    'source':'sample','schedule_id':'usd-v2','price_minor':row['facts']['price_minor'],
                    'currency':row['facts']['currency']},stage='quote')
                save()
            row = await request('catalog','POST',path+'/publish'+scope,body={
                'fee_quote_id':retained['quote']['id'],'rules_version':retained['quote']['schedule_id']},
                revision=row['revision'],stage='publish')
        assert row['status'] == 'published' and row['is_demo'] is True
        public.update(watch_id=row['physical_watch_id'],listing_published_revision=row['revision'],
                      listing_price_minor=row['facts']['price_minor'])
        (OUT/'proof-public.json').write_text(json.dumps(public,indent=2))
        print(json.dumps({'sample':True,'listing_id':row['id'],'revision':row['revision'],
                          'watch_id':row['physical_watch_id'],'status':row['status'],
                          'photos':len(row['photo_ids']),'actual_api_publication':True}))


if __name__ == '__main__':
    asyncio.run(main())
