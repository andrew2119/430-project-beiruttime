"""Deploy-applied sample businesses: one made-up sample dealer per sample set, and nothing else.

Each is written as the app's own onboarding writes it (business row, its first history entry and the
onboarded event), marked sample, with the deploy seed as the recorded actor, and every row is entered in
the seed's ownership record. It is not an assurance or review decision about any real company, and it
grants nothing by itself: staff access comes only from the membership seed, through the app's own
membership grant code. A pinned id held by a row the seed did not insert is logged and never touched.
"""
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime import demo_seed

ASSURANCE = 'DEMO-SEED-NO-ASSURANCE'
REASON = 'Sample business made by the deploy seed; not a review or assurance decision'


async def apply(settings):
    if not demo_seed.enabled():
        return {'skipped': 'switch'}
    counts = {'created': 0, 'kept': 0, 'foreign': 0}
    async with demo_seed.transaction(settings.database_url, 'identity-businesses') as tx:
        for business in demo_seed.businesses():
            if await demo_seed.owned(tx, 'l02_businesses', {'id': business.id}, business.key):
                counts['kept'] += 1
                continue
            row = await tx.fetchrow(
                '''INSERT INTO l02_businesses
                (id,legal_name,public_name,kind,capabilities,assurance_reference,sample,created_by)
                VALUES($1,$2,$2,'dealer',ARRAY['sales'],$3,true,$4) ON CONFLICT DO NOTHING RETURNING *''',
                business.id, business.public_name, ASSURANCE, demo_seed.ACTOR)
            if row is None:
                demo_seed.report('identity-businesses', f'foreign {business.key}: pinned id already in use')
                counts['foreign'] += 1
                continue
            await demo_seed.record(tx, business.key, 'l02_businesses', {'id': row['id']})
            history = await tx.fetchval('''INSERT INTO l02_business_history(business_id,actor_id,revision,action,reason)
                VALUES($1,$2,1,'onboarded',$3) RETURNING id''', row['id'], demo_seed.ACTOR, REASON)
            await demo_seed.record(tx, business.key, 'l02_business_history', {'id': history})
            async with demo_seed.events(tx, business.key):
                await enqueue(tx, EventEnvelope(
                    type='identity.business-onboarded.v1', source='identity', subject=str(row['id']),
                    request_id=demo_seed.REQUEST_ID,
                    data={'business_id': str(row['id']), 'kind': 'dealer', 'revision': 1, 'sample': True},
                ), ['catalog', 'service-operations'])
            counts['created'] += 1
    return counts
