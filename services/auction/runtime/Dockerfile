FROM python:3.11.14-slim AS dependencies
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="/opt/venv/bin:$PATH"
COPY services/auction/runtime/requirements.txt /tmp/requirements.txt
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
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/domain-contracts
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=dependencies /opt/domain-contracts /opt/domain-contracts
WORKDIR /app

FROM base AS test
ARG SERVICE_PATH=services/auction
COPY services/auction/runtime/requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt
COPY ${SERVICE_PATH}/runtime /app
COPY ${SERVICE_PATH}/modules /app/modules
COPY tests/foundation /foundation-tests
COPY tests/lanes /lane-tests
COPY contracts /contracts
USER app
CMD ["python", "/app/run_tests.py"]

FROM base AS runtime
ARG SERVICE_PATH=services/auction
COPY --chown=app:app ${SERVICE_PATH}/runtime/service_app /app/service_app
COPY --chown=app:app ${SERVICE_PATH}/modules /app/modules
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]
CMD ["uvicorn", "service_app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
