# Historical pre-integration browser harness

Final connected checks now use the integrated production app, canonical Account/Consent pages and the procedure in `../README.md`; they do not use this provisional entry point or its bootstrap sign-in form. The instructions below document the earlier frozen-contract proof only. The current browser matrix targets the canonical Account UI and must run against the real web app.

This test-only Next entry point composes the actual foundation shell, actual L07 screens and actual gateway. The frozen Identity browser session handoff was aliased before L01 landed on main. The small sign-in form calls real Identity operations; it grants no fabricated authority. Backend and gateway origin allowlists must both match the proof origin.

1. Start the isolated real services with `python3 tests/lanes/L07/connected-proof.py start`. It reuses the published Identity image, builds only the two owned services and provisions three restricted disposable databases. `refresh` updates only the owned services while retaining acknowledged records.
2. Copy published Identity `session.ts` to ignored `tests/lanes/L07/fixtures/session-runtime.ts`; link this directory's `node_modules` to `../../../../web/node_modules`.
3. From this directory run:

```sh
BT_PUBLIC_WEB_ORIGINS=http://localhost:3077 \
IDENTITY_API_URL=http://localhost:18101 \
PRICING_API_URL=http://localhost:18104 \
COMMUNICATIONS_API_URL=http://localhost:18108 \
./node_modules/.bin/next dev --webpack --port 3077
```

The matrix script creates fresh real sample buyers per emulated viewport, persists actual previews/drafts, and checks authenticated route geometry. Production still consumes L01's canonical registration/module after integration. This harness is provisional connected screen evidence, not a substitute for the final integrated production checkout.

During the disk-space hold, stop the owned proof with `docker compose -p bt-l07-proof -f tests/lanes/L07/.runtime/connected/compose.json stop`; do not remove shared containers, images or caches. `connected-proof.py stop` is the normal disposal helper and is not used during that hold.
