"""One-time, local administrative entry point; never exposed over HTTP."""
import argparse
import asyncio
from uuid import uuid4

import asyncpg
from bt_runtime.app.db import unit_of_work
from bt_runtime.app.settings import Settings

# Exact released platform capabilities, not business membership or a wildcard.
PERMISSIONS = (
    'identity.businesses.manage', 'identity.membership.manage',
    'identity.private-seller.assign', 'identity.private-seller.review',
    'identity.demo-mail.read',
    'moderation.review', 'moderation.assign', 'moderation.decide',
)


class BootstrapDenied(ValueError):
    pass


async def bootstrap(pool, email: str, reason: str):
    email = email.strip().lower()
    reason = reason.strip()
    if not email or len(email) > 254 or '@' not in email or not 10 <= len(reason) <= 500:
        raise BootstrapDenied('Provide an existing email and a reason of 10–500 characters.')
    # Serializes competing CLI invocations across processes. The permanent marker
    # prevents re-use even after a grant is revoked or the account is suspended.
    async with unit_of_work(pool, lock_key='identity:first-platform-operator:v1') as tx:
        used = await tx.fetchval('SELECT EXISTS(SELECT 1 FROM identity_operator_bootstrap)')
        existing = await tx.fetchval("""SELECT EXISTS(SELECT 1 FROM identity_access_grants
            WHERE organization_id IS NULL AND (role='operator'
            OR 'identity.businesses.manage'=ANY(permissions)))""")
        if used or existing:
            raise BootstrapDenied('First-operator bootstrap has already been used or an operator exists.')
        account = await tx.fetchrow('SELECT * FROM identity_accounts WHERE email=$1 FOR UPDATE', email)
        if not account or account['status'] != 'active':
            raise BootstrapDenied('Register an active account before running first-operator bootstrap.')
        subject, request_id = account['id'], 'bootstrap-' + str(uuid4())
        await tx.execute("""INSERT INTO identity_access_grants(id,subject_id,role,permissions)
            VALUES($1,$2,'operator',$3)""", uuid4(), subject, list(PERMISSIONS))
        await tx.execute('UPDATE identity_accounts SET access_revision=access_revision+1 WHERE id=$1', subject)
        await tx.execute("""INSERT INTO identity_operator_bootstrap(singleton,subject_id,reason,request_id)
            VALUES(1,$1,$2,$3)""", subject, reason, request_id)
        await tx.execute("""INSERT INTO identity_security_audit
            (id,actor_id,resource_id,action,outcome,request_id)
            VALUES($1,$2,$2,'operator.bootstrap','accepted',$3)""", uuid4(), subject, request_id)
        return str(subject)


async def run(email, reason):
    pool = await asyncpg.create_pool(Settings().database_url, min_size=1, max_size=1)
    try:
        return await bootstrap(pool, email, reason)
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(description='Grant the first platform operator to an existing registered account, once.')
    parser.add_argument('--email', required=True)
    parser.add_argument('--reason', required=True, help='Audited administrative justification (10–500 characters; no secrets).')
    args = parser.parse_args()
    try:
        subject = asyncio.run(run(args.email, args.reason))
    except BootstrapDenied as exc:
        parser.exit(1, str(exc) + '\n')
    print('First platform operator granted: ' + subject + '. Sign in again to refresh navigation.')


if __name__ == '__main__':
    main()
