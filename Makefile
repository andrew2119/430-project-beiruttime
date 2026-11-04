.PHONY: dev smoke test stop

dev:
	./scripts/dev.sh

smoke:
	./scripts/smoke.sh

test:
	python3 scripts/test-services.py
	corepack pnpm install --frozen-lockfile
	corepack pnpm --filter beirut-time-web typecheck
	corepack pnpm --filter beirut-time-web lint
	corepack pnpm --filter beirut-time-web test

stop:
	./infra/foundation/compose.sh stop
