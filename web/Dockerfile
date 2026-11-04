FROM node:22.21.1-alpine AS dependencies
WORKDIR /repo
RUN corepack enable && corepack prepare pnpm@10.20.0 --activate
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY web/package.json ./web/package.json
COPY packages/contracts-core/package.json ./packages/contracts-core/package.json
COPY packages/ui/package.json ./packages/ui/package.json
COPY packages/i18n/package.json ./packages/i18n/package.json
RUN pnpm install --frozen-lockfile

FROM dependencies AS build
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ARG FOUNDATION_PROXY_PROOF=0
ARG FOUNDATION_GATEWAY_PROOF=0
RUN if [ "$FOUNDATION_PROXY_PROOF" = 1 ]; then \
      mkdir -p 'web/app/(foundation-proxy-proof)/operations/moderation' 'web/app/(foundation-proxy-proof)/seller/dashboard'; \
      cp tests/foundation/fixtures/web/nested-page.tsx 'web/app/(foundation-proxy-proof)/operations/moderation/page.tsx'; \
      cp tests/foundation/fixtures/web/nested-page.tsx 'web/app/(foundation-proxy-proof)/seller/dashboard/page.tsx'; \
      cp web/registrations/L00.ts web/registrations/foundation-original.ts; \
      cp tests/foundation/fixtures/web/nested-registration.ts web/registrations/L00.ts; \
    elif [ "$FOUNDATION_GATEWAY_PROOF" = 1 ]; then \
      cp web/registrations/L00.ts web/registrations/foundation-original.ts; \
      cp tests/foundation/fixtures/web/gateway-registration.ts web/registrations/L00.ts; \
    fi && pnpm --filter beirut-time-web build

FROM node:22.21.1-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -g 10001 app && adduser -D -u 10001 -G app app
COPY --from=build --chown=app:app /repo/web/.next/standalone ./
COPY --from=build --chown=app:app /repo/web/.next/static ./web/.next/static
COPY --from=build --chown=app:app /repo/web/public ./web/public
USER app
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=6 CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]
CMD ["node", "web/server.js"]
