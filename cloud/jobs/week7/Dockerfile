FROM python:3.11-slim-bookworm@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DBT_PROFILES_DIR=/app/dbt/dataforge \
    DBT_TARGET_PATH=/tmp/dbt/target \
    DBT_LOG_PATH=/tmp/dbt/logs \
    DBT_PACKAGE_INSTALL_PATH=/tmp/dbt/packages

WORKDIR /app/dbt/dataforge

COPY cloud/jobs/week7/requirements.lock /app/cloud/jobs/week7/requirements.lock
RUN python -m pip install --no-cache-dir -r /app/cloud/jobs/week7/requirements.lock \
    && useradd --system --create-home --uid 10001 dataforge \
    && mkdir -p /tmp/dbt/target /tmp/dbt/logs /tmp/dbt/packages \
    && chown -R 10001:10001 /tmp/dbt

COPY dbt/dataforge/ /app/dbt/dataforge/
RUN cp /app/dbt/dataforge/profiles.example.yml /app/dbt/dataforge/profiles.yml \
    && chown -R 10001:10001 /app/dbt/dataforge

USER 10001:10001
ENTRYPOINT ["dbt"]
