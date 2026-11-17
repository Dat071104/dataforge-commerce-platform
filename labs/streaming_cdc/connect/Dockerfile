ARG CONNECT_BASE_IMAGE=confluentinc/cp-kafka-connect:7.9.11.amd64@sha256:82ef611a6547fd513cb52891326c3d5a8a5e30c8ea511e71f9813c93ad98482f
FROM ${CONNECT_BASE_IMAGE}

ARG DEBEZIUM_VERSION=3.1.3

USER root
RUN confluent-hub install --no-prompt "debezium/debezium-connector-postgresql:${DEBEZIUM_VERSION}"
USER appuser
