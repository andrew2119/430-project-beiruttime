# Kubernetes demo

The whole site (the nine services, their migrations, one Postgres and the web front end) on a throwaway [kind](https://kind.sigs.k8s.io/) cluster, built from the current checkout.

```sh
infra/k8s/demo.sh up     # build, start, migrate, deploy and smoke check; the site is at http://127.0.0.1:3000
infra/k8s/demo.sh down   # delete the cluster and everything in it
```

It needs Docker with buildx, kind, kubectl, jq, yq, openssl, curl, git and python3.
Every password and signing key is generated in the run for demo use only and stays inside the cluster.
A new cluster starts with empty databases, and they disappear with the cluster.
`up` reuses a cluster that already exists, with its Secrets and database data, so run `down` first for a fresh start.

`demo.sh check` runs first and needs Compose, kubectl and yq to produce its inputs, but no cluster; `check.py` itself needs only Python.

`.github/workflows/kubernetes.yml` runs the same steps on a GitHub-hosted runner on every push to main, on pull requests that change this folder or the workflow, and from the Run workflow button.
It runs at most two at a time, one for main pushes and manual runs and one for all pull requests.
A running main or manual run is never cancelled, and only the newest run waiting behind it is kept.
A newer pull request run cancels the one in progress, whichever pull request it belongs to.

| File | What it is |
| --- | --- |
| `kind.yaml` | One-node cluster; publishes the site on 127.0.0.1:3000 only. |
| `kustomization.yaml` | The stack: `kubectl kustomize infra/k8s` renders every object below. |
| `namespace.yaml` | The `beirut-time` namespace everything lives in. |
| `postgres.yaml` | Postgres with the Compose image, init script and health check. |
| `services/<service>.yaml` | Per service: its migration Job, its Deployment and its in-cluster address. |
| `web.yaml` | The site and its NodePort, the demo's one entry point. |
| `demo.sh` | Every step, from building the images to the smoke check and the run summary. |
| `check.py` | Fails when a manifest drifts from `infra/railway/` or the Compose stack, or when the cluster would publish anything beyond the site on 127.0.0.1:3000. |

When a service gains a variable in Compose or a new command in `infra/railway/<service>.json`, or a new service appears, `demo.sh check` names what to change here.
