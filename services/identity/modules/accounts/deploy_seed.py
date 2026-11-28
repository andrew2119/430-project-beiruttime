"""Deploy-applied sample accounts: ordinary accounts, one per demo tab and set, that no password opens.

Each account is recorded in the seed's ownership record, which marks it seed-only: the account routes
refuse password sign-in, password recovery and password reset for it (`security.seed_only`), so the
password-free sample link is the only way in. Its stored hash is a fixed value no password can match.
Every account is created plain, the Operator sample included: nothing here grants a role, operator
power, a business membership or a review decision. The Business staff sample's only access comes later
from the membership seed, scoped to its own sample business.
A pinned id or address that already exists without the seed's ownership record is someone else's: it is
logged as foreign and never read further, updated or reused by any later seed step.
"""
from bt_runtime import demo_seed
from .security import event

# Not a scrypt encoding, so password_matches can never accept it; the ownership record is the real marker.
NO_PASSWORD = 'seed-only$no-password'


async def apply(settings):
    if not demo_seed.enabled():
        return {'skipped': 'switch'}
    counts = {'created': 0, 'kept': 0, 'foreign': 0}
    async with demo_seed.transaction(settings.database_url, 'identity-accounts') as tx:
        for account in demo_seed.accounts():
            if await demo_seed.owned(tx, 'identity_accounts', {'id': account.id}, account.key):
                counts['kept'] += 1
                continue
            created = await tx.fetchval('''INSERT INTO identity_accounts(id,email,display_name,password_hash)
                VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING id''',
                account.id, account.email, account.display_name, NO_PASSWORD)
            if created is None:
                # The id or the address belongs to an account the seed did not create: leave it alone.
                demo_seed.report('identity-accounts', f'foreign {account.key}: pinned id or address already in use')
                counts['foreign'] += 1
                continue
            await demo_seed.record(tx, account.key, 'identity_accounts', {'id': created})
            # What registration writes: a security audit row and the account-registered event.
            audit = await tx.fetchval('''INSERT INTO identity_security_audit VALUES($1,NULL,$2,$3,'accepted',$4,now())
                ON CONFLICT DO NOTHING RETURNING id''', demo_seed.seed_id(account.key + ':audit'), created,
                'demo-seed.account-create', demo_seed.REQUEST_ID)
            if audit is not None:
                await demo_seed.record(tx, account.key, 'identity_security_audit', {'id': audit})
            async with demo_seed.events(tx, account.key):
                await event(tx, demo_seed.REQUEST, created, 'identity.account-registered.v1')
            counts['created'] += 1
    return counts
