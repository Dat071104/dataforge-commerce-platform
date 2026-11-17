ARG CONNECT_BASE_IMAGE=confluentinc/cp-kafka-connect:7.9.11.amd64@sha256:82ef611a6547fd513cb52891326c3d5a8a5e30c8ea511e71f9813c93ad98482f
FROM ${CONNECT_BASE_IMAGE}

ARG DEBEZIUM_VERSION=3.1.3.Final
ARG DEBEZIUM_PLUGIN_SHA256=2ed3f0b1dd3ee3b1180cc975e0464b675cca5f972db6a9ae3a75f5376874f652

USER root
RUN set -eux; \
    archive="/tmp/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz"; \
    url="https://repo.maven.apache.org/maven2/io/debezium/debezium-connector-postgres/${DEBEZIUM_VERSION}/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz"; \
    curl --fail --location --silent --show-error --retry 3 "$url" --output "$archive"; \
    echo "${DEBEZIUM_PLUGIN_SHA256}  ${archive}" | sha256sum --check -; \
    install -d /usr/share/confluent-hub-components/debezium-postgres; \
    tar -xzf "$archive" --directory /usr/share/confluent-hub-components/debezium-postgres --strip-components=1; \
    test -s "/usr/share/confluent-hub-components/debezium-postgres/debezium-connector-postgres-${DEBEZIUM_VERSION}.jar"; \
    rm -f "$archive"
USER appuser
