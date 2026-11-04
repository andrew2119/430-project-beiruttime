# Isolated module proof only. L01 alone owns the authoritative Identity runtime.
ARG FOUNDATION_TEST_IMAGE=beirut-time/l02-foundation-test:local
FROM ${FOUNDATION_TEST_IMAGE}
USER root
COPY services/identity/modules /app/modules
COPY tests/lanes/L02/fixtures/runtime/service_app/identity.py /app/service_app/identity.py
COPY tests/lanes/L02/*.py /lane-tests/L02/
COPY tests/lanes/L02/fixtures /lane-tests/L02/fixtures
USER app
ENV BT_TEST_LANE=L02 BT_MODULES_PATH=/app/modules
