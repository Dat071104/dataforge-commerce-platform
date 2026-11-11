FROM python:3.11.18-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH="/usr/lib/jvm/java-17-openjdk-amd64/bin:${PATH}" \
    PYSPARK_PYTHON=python \
    PYSPARK_DRIVER_PYTHON=python

RUN apt-get update \
    && apt-get install --no-install-recommends -y openjdk-17-jre-headless tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --disable-pip-version-check \
      pyspark==3.5.9 \
      delta-spark==3.3.3 \
    && useradd --system --uid 10001 --create-home spark

# PyArrow supplies the bounded independent TLC partition reader; pytest runs
# the network-free fixture suite in the same pinned container used locally.
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      pyarrow==23.0.1 \
      pytest==9.2.0

WORKDIR /workspace
USER 10001:10001

ENTRYPOINT ["python"]
