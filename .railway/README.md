# Railway infrastructure

`.railway/railway.ts` describes the existing `beirut-time` environment, using one deployment descriptor per application under `infra/railway/`. PostgreSQL and its persistent volume are included so a whole-project plan cannot accidentally omit them. Generated public domains and all variable values remain in Railway.

Use Railway CLI **5.42.1 or newer**:

```sh
npm --prefix .railway ci
railway config plan
# Review the entire plan, especially any deletion, before applying:
railway config apply
```

The checked-in configuration produces a **No changes** plan against the initial live deployment. Environment variables are explicitly unmanaged: planning/applying this graph does not read, replace or delete credentials.

Application deployments are already connected to GitHub `main` with service-specific watch paths and do not require a workflow or IaC apply. A change to infrastructure intent must be separately reviewed and applied. Do not select the JSON descriptors as legacy Railway config files: new services cannot use that deprecated mechanism. Do not omit existing resources or enable variable management casually.
