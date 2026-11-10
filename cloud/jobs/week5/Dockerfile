FROM python:3.11-slim-bookworm@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY cloud/jobs/week5/requirements.txt /app/cloud/jobs/week5/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check \
      -r /app/cloud/jobs/week5/requirements.txt \
    && useradd --system --create-home --uid 10001 dataforge

COPY src/dataforge/__init__.py /app/src/dataforge/__init__.py
COPY src/dataforge/settings.py /app/src/dataforge/settings.py
COPY src/dataforge/cloud/__init__.py /app/src/dataforge/cloud/__init__.py
COPY src/dataforge/cloud/adapters.py /app/src/dataforge/cloud/adapters.py
COPY src/dataforge/cloud/contracts.py /app/src/dataforge/cloud/contracts.py
COPY src/dataforge/cloud/google_cloud.py /app/src/dataforge/cloud/google_cloud.py
COPY src/dataforge/incremental/__init__.py /app/src/dataforge/incremental/__init__.py
COPY src/dataforge/incremental/batch.py /app/src/dataforge/incremental/batch.py
COPY src/dataforge/incremental/bronze.py /app/src/dataforge/incremental/bronze.py
COPY cloud/jobs/week5/consumer.py /app/cloud/jobs/week5/consumer.py
COPY cloud/sql_bigquery/week5/publish.sql /app/cloud/sql_bigquery/week5/publish.sql

USER 10001:10001
ENTRYPOINT ["python", "/app/cloud/jobs/week5/consumer.py"]
