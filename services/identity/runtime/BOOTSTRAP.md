# First platform operator

Open `/en/account` (or `/ar/account`), choose **Create an account**, and register an ordinary account. After Identity migrations, run this local administrative command in the Identity runtime:

```sh
./infra/foundation/compose.sh exec -T identity python -m service_app.bootstrap_operator \
  --email operator@example.test --reason 'Authorize initial course demonstration operator'
```

Sign in again. No password, session, fixture, or handwritten SQL is needed by the command. It grants only explicit released platform permissions; it does not verify the email, grant business membership, approve a seller, or invent commercial outcomes. Contact-delivery and recovery-mail viewing are explicitly simulated demo capabilities.

The one-time seal, reason, subject and security audit are committed in one transaction under a process-independent lock. Competing invocations cannot create two operators. An existing operator (including a revoked grant) or an already-used seal denies re-use. Missing/suspended accounts and invalid reasons do not consume the seal. Subsequent official-business and colleague grants use the authenticated operator screens. Never delete the seal to recover access; use a separately authorized administrative recovery procedure.
