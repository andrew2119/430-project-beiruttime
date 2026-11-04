ARG AUCTION_TEST_IMAGE=beirut-time/auction:local
FROM ${AUCTION_TEST_IMAGE}
USER root
RUN rm -rf /app/modules
COPY services/communications/modules/bid-notices /app/modules/bid-notices
COPY services/auction/modules /app/auction-modules
ENV PYTHONPATH=/opt/domain-contracts:/app:/lane-tests/L05/auction
COPY tests/lanes/L05/communications /lane-tests/L05/communications
USER app
CMD ["python", "-m", "pytest", "-c", "/app/pyproject.toml", "/lane-tests/L05/communications", "-q", "-o", "cache_dir=/tmp/pytest-cache"]
