"""Deploy-applied pending private-seller case for each sample seller, with sample evidence text.

It writes what a submission writes (case, two evidence rows, audit, submitted event) and nothing a
review writes: no reviewer assignment, no decision, no grant. The operator reviews it in the app.
It attaches a case only to the seed's own active sample seller account, proven by the ownership record and by
the pinned id and address, and it never touches a case it did not insert. The account is locked first, without
waiting and as the app's own account changes lock it, and only then checked, so the account checked is the one
that stays locked until the case commits; a live writer holding it skips the seller (busy).
"""
import hashlib
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime import demo_seed

EVIDENCE = {
    'identity': 'Sample identity record for the demonstration; not a real document.',
    'possession': 'Sample possession note for the demonstration; not a physical inspection.',
}
PAYOUT = 'DEMO-SAMPLE-RECIPIENT'


async def apply(settings):
    if not demo_seed.enabled():
        return {'skipped': 'switch'}
    counts = {'created': 0, 'kept': 0, 'foreign': 0, 'no_account': 0, 'busy': 0}
    async with demo_seed.transaction(settings.database_url, 'identity-private-seller') as tx:
        for seller in demo_seed.accounts('seller'):
            key = demo_seed.demo_key(seller.sample_set, 'application', 'seller')
            case_id = demo_seed.seed_id(key)
            if await demo_seed.owned(tx, 'identity_private_applications', {'id': case_id}, key):
                counts['kept'] += 1
                continue
            found = await demo_seed.locked_owned(tx, 'identity_accounts', {'id': seller.id}, seller.key,
                                                 "t.email=$4 AND t.status='active'", (seller.email,), 'FOR UPDATE')
            if found is None:
                demo_seed.report('identity-private-seller', f'busy {key}: the seller account is being changed')
                counts['busy'] += 1
                continue
            if not found:
                counts['no_account'] += 1
                continue
            evidence_ids = [demo_seed.seed_id(f'{key}:evidence:{kind}') for kind in EVIDENCE]
            if await tx.fetchval('SELECT 1 FROM identity_private_evidence WHERE id=ANY($1::uuid[])', evidence_ids):
                demo_seed.report('identity-private-seller', f'foreign {key}: a pinned evidence id is already in use')
                counts['foreign'] += 1
                continue
            case = await tx.fetchrow('''INSERT INTO identity_private_applications
                (id,subject_id,revision,status,identity_name,contact,payout_reference)
                VALUES($1,$2,1,'pending',$3,$4,$5) ON CONFLICT DO NOTHING RETURNING *''',
                case_id, seller.id, seller.display_name, seller.email, PAYOUT)
            if case is None:
                # The sample seller already has a case it made in the app, or another row holds the id.
                demo_seed.report('identity-private-seller', f'foreign {key}: a case the seed did not create exists')
                counts['foreign'] += 1
                continue
            await demo_seed.record(tx, key, 'identity_private_applications', {'id': case['id']})
            for evidence_id, (kind, value) in zip(evidence_ids, EVIDENCE.items()):
                content = value.encode()
                evidence = await tx.fetchval('''INSERT INTO identity_private_evidence
                    (id,application_id,subject_id,kind,content,sha256) VALUES($1,$2,$3,$4,$5,$6) RETURNING id''',
                    evidence_id, case['id'], seller.id, kind, content, hashlib.sha256(content).hexdigest())
                await demo_seed.record(tx, key, 'identity_private_evidence', {'id': evidence})
            audit = await tx.fetchval('''INSERT INTO identity_security_audit VALUES($1,NULL,$2,$3,'accepted',$4,now())
                ON CONFLICT DO NOTHING RETURNING id''', demo_seed.seed_id(key + ':audit'), case['id'],
                'demo-seed.private-seller-submit', demo_seed.REQUEST_ID)
            if audit is not None:
                await demo_seed.record(tx, key, 'identity_security_audit', {'id': audit})
            async with demo_seed.events(tx, key):
                await enqueue(tx, EventEnvelope(type='identity.private-seller-submitted.v1', source='identity',
                    subject=str(case['id']), request_id=demo_seed.REQUEST_ID,
                    data={'application_id': str(case['id']), 'revision': case['revision']}), ['communications'])
            counts['created'] += 1
    return counts
