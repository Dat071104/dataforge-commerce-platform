# Runtime base is pinned to the reviewed Airflow 3.4.0 Python 3.11 manifest.
FROM apache/airflow:3.4.0-python3.11@sha256:be92e15d57c5be726fc39a91cd09cce8f7488483b67979e0fb74c1a2c7cfb4e2

COPY --chown=airflow:root labs/airflow_reference/requirements-cloud.txt /tmp/requirements-cloud.txt
RUN python -c "from importlib.metadata import version; from pathlib import Path; expected = dict(line.strip().split('==', 1) for line in Path('/tmp/requirements-cloud.txt').read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')); actual = {package: version(package) for package in expected}; assert actual == expected, f'GCP client versions do not match pinned Airflow base: expected={expected}, actual={actual}'"

COPY --chown=airflow:root labs/airflow_reference/dags/ /opt/airflow/dags/
COPY --chown=airflow:root deploy/airflow_vm/ /opt/dataforge/airflow_vm/
RUN chmod 0755 /opt/dataforge/airflow_vm/bootstrap.py

USER airflow
