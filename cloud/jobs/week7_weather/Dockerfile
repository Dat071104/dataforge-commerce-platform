FROM python:3.11-slim-bookworm@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY cloud/jobs/week7_weather/requirements.lock /app/cloud/jobs/week7_weather/requirements.lock
RUN python -m pip install --no-cache-dir -r /app/cloud/jobs/week7_weather/requirements.lock \
    && useradd --system --create-home --uid 10001 dataforge

COPY src/dataforge/__init__.py /app/src/dataforge/__init__.py
COPY src/dataforge/settings.py /app/src/dataforge/settings.py
COPY src/dataforge/weather.py /app/src/dataforge/weather.py
COPY cloud/jobs/week7_weather/weather_job.py /app/cloud/jobs/week7_weather/weather_job.py

USER 10001:10001
ENTRYPOINT ["python", "/app/cloud/jobs/week7_weather/weather_job.py"]
