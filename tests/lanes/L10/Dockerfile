# Lane-only validation overlay; L03 remains the sole production Catalog runtime owner.
ARG FOUNDATION_IMAGE=beirut-time/l10-foundation:test
FROM ${FOUNDATION_IMAGE} AS test
COPY services/catalog/modules/options /app/modules/options
COPY tests/lanes/L10 /lane-tests/L10

FROM test AS browser
ENV BT_MODULES_PATH=/tmp/l10-core-baseline
CMD ["python", "/lane-tests/L10/browser_server.py"]
