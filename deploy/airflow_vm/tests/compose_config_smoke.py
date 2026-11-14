"""Check the resolved Compose model does not embed test secret payloads."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PLACEHOLDER_FILES = (
    "fernet_key",
    "metadata_db_password",
    "admin_password",
)
EXPECTED_CONFIG_COMMANDS = (
    "AIRFLOW__CORE__FERNET_KEY_CMD",
    "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN_CMD",
    "AIRFLOW__API__SECRET_KEY_CMD",
    "AIRFLOW__API_AUTH__JWT_SECRET_CMD",
)


def main() -> None:
    secret_dir_value = os.environ.get("DATAFORGE_SECRET_DIR")
    if not secret_dir_value:
        raise RuntimeError("Compose smoke test requires disposable placeholder files")
    secret_dir = Path(secret_dir_value)
    placeholder_values = [
        (secret_dir / name).read_text(encoding="utf-8") for name in PLACEHOLDER_FILES
    ]
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            "deploy/airflow_vm/compose.yaml",
            "config",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Docker Compose validation failed with exit {result.returncode}; output suppressed"
        )
    compose_source = Path("deploy/airflow_vm/compose.yaml").read_text(encoding="utf-8")
    if "restart:" in compose_source:
        raise AssertionError("Compose containers must not compete with systemd restart policy")
    if "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN:" in compose_source:
        raise AssertionError("Compose must not set the database URL directly in the container environment")
    systemd_unit = Path("deploy/airflow_vm/dataforge-airflow.service").read_text(
        encoding="utf-8"
    )
    if "Type=simple" not in systemd_unit or "Restart=on-failure" not in systemd_unit:
        raise AssertionError("systemd must supervise the attached Compose runtime")
    for name in EXPECTED_CONFIG_COMMANDS:
        if name not in result.stdout:
            raise AssertionError(f"Compose configuration is missing {name}")
    if "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN:" in result.stdout:
        raise AssertionError("Resolved Compose model overrides the file-backed database URL")
    for name in PLACEHOLDER_FILES:
        if name not in result.stdout:
            raise AssertionError(f"Resolved Compose model is missing the {name} secret mount")
    if any(value in result.stdout for value in placeholder_values):
        raise AssertionError("Resolved Compose model contains a secret placeholder value")
    print("compose_config_valid=True secret_values_absent=True tmpfs_mount_paths_present=True")


if __name__ == "__main__":
    main()
