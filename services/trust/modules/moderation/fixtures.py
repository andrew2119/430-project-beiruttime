"""Opt-in sample report through the real command, never a seeded decision."""
import os
from uuid import UUID
from bt_bulkheads import DependencyClient, Unavailable


async def seed(settings):
    listing=UUID(os.environ['BT_SAMPLE_LISTING_ID'])
    token=os.environ['BT_SAMPLE_REPORTER_TOKEN']
    client=DependencyClient('trust',os.getenv('BT_TRUST_URL','http://trust:8000'),timeout=2,concurrency=1)
    try:
        response=await client.request('POST','/v1/moderation/reports',headers={
            'Authorization':'Bearer '+token,'Idempotency-Key':'sample-report-'+listing.hex},json={
            'target_kind':'listing','target_id':str(listing),'category':'misleading',
            'evidence':'SAMPLE CONTENT — review the condition description on this sample listing.'})
        if isinstance(response,Unavailable) or response.status_code not in (200,201):
            raise RuntimeError('Sample report was not confirmed by Trust')
    finally:
        await client.aclose()
