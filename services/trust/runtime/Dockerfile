FROM python:3.11.14-slim AS dependencies
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="/opt/venv/bin:$PATH"
COPY services/trust/runtime/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages/contracts-core /tmp/packages/contracts-core
COPY packages/bulkheads /tmp/packages/bulkheads
COPY packages/events /tmp/packages/events
COPY packages/runtime /tmp/packages/runtime
RUN pip install --no-cache-dir /tmp/packages/contracts-core /tmp/packages/bulkheads /tmp/packages/events /tmp/packages/runtime
COPY packages /tmp/repository/packages
COPY contracts /tmp/repository/contracts
COPY infra/foundation/discover-contracts.py infra/foundation/package-contracts.py /tmp/repository/infra/foundation/
RUN python /tmp/repository/infra/foundation/package-contracts.py /opt/domain-contracts

FROM python:3.11.14-slim AS base
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/domain-contracts BT_SERVICE_NAME=trust
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=dependencies /opt/domain-contracts /opt/domain-contracts
WORKDIR /app

FROM node:22.21.1-bookworm-slim AS test-javascript
RUN install -D -m 0644 -t /runtime-libs/ /usr/lib/*/libstdc++.so.6 /lib/*/libgcc_s.so.1

FROM base AS test
ARG SERVICE_PATH=services/trust
COPY services/trust/runtime/requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt
COPY ${SERVICE_PATH}/runtime /app
COPY ${SERVICE_PATH}/modules /app/modules
COPY tests/foundation /foundation-tests
COPY tests/lanes /lane-tests
COPY contracts /contracts
COPY --from=test-javascript /usr/local/bin/node /usr/local/bin/node
COPY --from=test-javascript /runtime-libs/ /usr/local/lib/
RUN ldconfig
COPY --from=dependencies /tmp/repository/packages /wiring-inputs/packages
COPY contracts /wiring-inputs/contracts
COPY infra/foundation/discover-contracts.py /wiring-inputs/infra/foundation/discover-contracts.py
COPY infra/railway/trust.json /wiring-inputs/infra/railway/trust.json
COPY web/scripts/generate-nav.mjs /wiring-inputs/web/scripts/generate-nav.mjs
COPY web/registrations /wiring-inputs/web/registrations
COPY services/trust/runtime/run_tests.py /wiring-inputs/services/trust/runtime/run_tests.py
USER app
RUN ["node", "--version"]
CMD ["python", "/app/run_tests.py"]

FROM base AS runtime
ARG SERVICE_PATH=services/trust
COPY --chown=app:app ${SERVICE_PATH}/runtime/service_app /app/service_app
COPY --chown=app:app ${SERVICE_PATH}/modules /app/modules
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]
CMD ["uvicorn", "service_app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
