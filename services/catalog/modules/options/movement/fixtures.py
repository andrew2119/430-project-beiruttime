"""Publish one explicitly sample brand movement using the owning application operation."""
import os
from uuid import UUID
import httpx
from bt_bulkheads import DependencyClient, Unavailable


async def seed(settings):
    brand = UUID(os.environ['BT_DEMO_ORGANIZATION_ID'])
    option = UUID('00000000-0011-4000-8000-000000000003')
    identity = DependencyClient('identity-sample-check', os.getenv('IDENTITY_API_URL', 'http://identity:8000'), timeout=1, concurrency=1)
    try:
        proof = await identity.request('GET', f'/v1/businesses/{brand}')
        if isinstance(proof, Unavailable) or proof.status_code != 200 or proof.json().get('sample') is not True:
            raise ValueError('An explicitly sample onboarded brand is required')
    finally:
        await identity.aclose()
    async with httpx.AsyncClient(base_url=os.getenv('BT_FIXTURE_API_URL', 'http://127.0.0.1:8000'), timeout=4) as client:
        result = await client.put(f'/v1/options/movement/{option}', headers={'Authorization': 'Bearer ' + os.environ['BT_DEMO_BUSINESS_TOKEN'], 'Idempotency-Key': 'movement-sample-v1'}, json={
            'brand_id': str(brand), 'expected_revision': 0, 'label_en': 'Automatic · sample caliber', 'label_ar': 'أوتوماتيكية · عيار تجريبي',
            'caliber': 'DEMO-A01', 'cases': ['DEMO-CASE-40'], 'dials': ['DEMO-DIAL-3'], 'hands': ['DEMO-HANDS-3'],
            'functions': ['hours', 'minutes', 'seconds'], 'quote_minor': 25000, 'currency': 'USD', 'active': True})
        result.raise_for_status()
        return result.json()
