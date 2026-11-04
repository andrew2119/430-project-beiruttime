"""Explicit sample imports through real authorized commands; never startup seeds."""
import os
from uuid import UUID
import httpx
from bt_bulkheads import DependencyClient, Unavailable


async def seed(settings):
    entries = [('brand', UUID(os.environ['BT_DEMO_ORGANIZATION_ID']))]
    if os.getenv('BT_DEMO_DEALER_ID'):
        entries.append(('dealer', UUID(os.environ['BT_DEMO_DEALER_ID'])))
    identity = DependencyClient('identity-sample-check', os.getenv('IDENTITY_API_URL', 'http://identity:8000'), timeout=1, concurrency=1)
    try:
        async with httpx.AsyncClient(base_url=os.getenv('BT_FIXTURE_API_URL', 'http://127.0.0.1:8000'), timeout=4) as client:
            results = []
            for kind, organization_id in entries:
                proof = await identity.request('GET', f'/v1/businesses/{organization_id}')
                if isinstance(proof, Unavailable) or proof.status_code != 200 or proof.json().get('sample') is not True:
                    raise ValueError('An explicitly sample onboarded business is required')
                result = await client.put(f'/v1/directory/businesses/{organization_id}', headers={
                    'Authorization': 'Bearer ' + os.environ['BT_DEMO_BUSINESS_TOKEN'],
                    'Idempotency-Key': 'directory-sample-' + kind + '-v1'}, json={
                    'expected_revision': 0,
                    'capabilities': ['maintenance', 'cleaning', 'repair'] + (['customization'] if kind == 'brand' else []),
                    'contact': 'sample@example.invalid',
                    'visit_en': 'Demo content · Beirut · visits by arrangement only.',
                    'visit_ar': 'محتوى تجريبي · بيروت · الزيارات بترتيب مسبق فقط.',
                    'scope_en': 'Sample declared capabilities. Assessment and a separate quote are required; no work or appointment is confirmed.',
                    'scope_ar': 'قدرات معلنة تجريبية. يلزم التقييم وعرض سعر منفصل؛ لا يتم تأكيد أي عمل أو موعد.',
                    'published': True})
                result.raise_for_status()
                results.append(result.json())
            return {'profiles': results}
    finally:
        await identity.aclose()
